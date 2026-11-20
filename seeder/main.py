"""One-shot job: loads the demo organisation through the gateway's own APIs.

Each step is recorded in the gateway once it has succeeded, so a restart carries on where
the last run stopped and a second run loads nothing twice.
"""

import json
import logging
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from random import Random

from pydantic import Field
from pydantic_settings import BaseSettings

from seeder.activity.logs import dns_log, plan_visits, squid_log
from seeder.activity.prompts import batches, plan_prompts
from seeder.activity.timeline import Timeline
from seeder.gateway import Gateway, GatewayError
from seeder.world import DATA_DIR, World, load_world

log = logging.getLogger("seeder")

ADMIN = "a.bilas"


class Settings(BaseSettings):
    seed_demo_data: bool = Field(default=False, validation_alias="SEED_DEMO_DATA")
    gateway_url: str = Field(default="http://gateway:8000", validation_alias="GATEWAY_URL")
    wait_seconds: float = Field(default=300.0, validation_alias="SEEDER_WAIT_SECONDS")


def load_directory(gateway: Gateway, world: World) -> None:
    users = [
        {"user_id": e.user_id, "display_name": e.display_name, "team": e.team}
        for e in world.employees
    ]
    networks = [{"cidr": team.cidr, "team": team.name} for team in world.teams]
    gateway.import_directory(users, networks)
    log.info("directory: %d employees in %d teams", len(users), len(networks))


def sync_terms(gateway: Gateway) -> None:
    result = gateway.sync_terms()
    log.info("protected terms: %s imported from the CRM", result.get("imported"))


def upload_name(file: str) -> str:
    """Python sources are stored with a `.txt` suffix; the gateway gets the real name."""
    return file.removesuffix(".txt") if file.endswith(".py.txt") else file


def load_corpus(gateway: Gateway, corpus_dir: Path) -> None:
    manifest = (corpus_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    duplicates = 0
    for row in map(json.loads, manifest):
        content = (corpus_dir / row["file"]).read_bytes()
        duplicates += gateway.upload_document(
            upload_name(row["file"]), content, row["title"], row["category"]
        )
    log.info("corpus: %d documents fingerprinted, %d already there", len(manifest), duplicates)


def load_pattern(gateway: Gateway, world: World) -> None:
    pattern = world.project_pattern
    if pattern.name in gateway.pattern_names():
        log.info("custom pattern: already there")
        return
    gateway.add_pattern(pattern.name, pattern.regex, pattern.data_type)
    log.info("custom pattern: %s added", pattern.name)


def load_logs(gateway: Gateway, world: World, timeline: Timeline) -> None:
    rng = Random(f"{world.seed}:logs")
    visits = plan_visits(world, gateway.tools(), timeline, rng)
    for kind, content in (("squid", squid_log(visits, rng)), ("dns", dns_log(visits))):
        result = gateway.upload_log(f"{kind}-14-days.log", content, kind)
        log.info(
            "%s log: %s lines, %s matched, %s new tools",
            kind,
            result.get("lines"),
            result.get("matched"),
            result.get("new_tools"),
        )


def load_prompts(gateway: Gateway, world: World, timeline: Timeline, done: set[str]) -> None:
    prompts = plan_prompts(world, gateway.tools(), timeline, DATA_DIR / "corpus")
    for number, batch in enumerate(batches(prompts), 1):
        step = f"prompts-{number:02d}"
        if step in done:
            continue
        result = gateway.ingest_prompts([prompt.record() for prompt in batch])
        gateway.mark(step)
        log.info(
            "%s: %s prompts inspected, actions %s",
            step,
            result.get("ingested"),
            result.get("actions"),
        )


def seed(gateway: Gateway, world: World, now: datetime) -> None:
    timeline = Timeline(now)
    done = gateway.seed_state()
    steps: tuple[tuple[str, Callable[[], None]], ...] = (
        ("directory", lambda: load_directory(gateway, world)),
        ("terms", lambda: sync_terms(gateway)),
        ("corpus", lambda: load_corpus(gateway, DATA_DIR / "corpus")),
        ("pattern", lambda: load_pattern(gateway, world)),
        ("logs", lambda: load_logs(gateway, world, timeline)),
    )
    for step, run in steps:
        if step in done:
            log.info("%s: already loaded", step)
            continue
        run()
        gateway.mark(step)
    load_prompts(gateway, world, timeline, done)


def run(settings: Settings, gateway: Gateway, now: datetime) -> int:
    """Returns the process exit code. The directory is always loaded, because team names and
    the lookup of who sent an event need it; the rest of the organisation only on request."""
    try:
        gateway.wait_until_ready(settings.wait_seconds)
        gateway.sign_in(ADMIN)
        world = load_world()
        if settings.seed_demo_data:
            seed(gateway, world, now)
        elif "directory" not in gateway.seed_state():
            load_directory(gateway, world)
            gateway.mark("directory")
    except GatewayError as exc:
        log.error("seeding failed: %s", exc)
        return 1
    if settings.seed_demo_data:
        log.info("the demo organisation is loaded")
    else:
        log.info("the directory is loaded; SEED_DEMO_DATA is false, so nothing else")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings()
    gateway = Gateway(settings.gateway_url)
    try:
        return run(settings, gateway, datetime.now(UTC))
    finally:
        gateway.close()


if __name__ == "__main__":
    sys.exit(main())
