"""The demo organisation's confidential corpus: the documents the seeder fingerprints."""

from random import Random

from seeder.compose.context import (
    client_party,
    draw_numbers,
    firm_slots,
    number_slots,
    party_slots,
    project_slots,
    staff_slots,
)
from seeder.compose.library import CONTENT, Document, compose, load_library
from seeder.compose.slots import Language, Slot
from seeder.names import person_from
from seeder.world import Client, Project, World

# (kind, documents per language, sections per document)
PROSE_PLAN = (("contract", 6, 10), ("proposal", 4, 10), ("financial", 3, 9), ("meeting", 3, 9))
# (template, project)
SOURCE_PLAN = (
    ("ledger_sync.py", "Helix"),
    ("invoice_matcher.py", "Kyma"),
    ("ticketRouter.ts", "Pharos"),
    ("documentPortal.ts", "Tessera"),
    ("RateCardService.java", "Meridian"),
    ("forecast.go", "Kyma"),
    ("pipeline_schema.sql", "Argo"),
    ("RenewalNotifier.cs", "Argo"),
)
LANGUAGES: tuple[Language, Language] = ("el", "en")


def key_accounts(world: World, language: Language) -> list[Client]:
    """The company clients that have documents. The first Greek one is the scene 1 client."""
    return [c for c in world.clients if c.kind == "company" and c.language == language]


def _project_for(world: World, client: Client, index: int) -> Project:
    own = [project for project in world.projects if project.team == client.team]
    return own[index % len(own)] if own else world.projects[index % len(world.projects)]


def document_slots(
    world: World, client: Client, index: int, rng: Random
) -> dict[Language, dict[str, Slot]]:
    """The slots of one corpus document, in both languages from the same facts."""
    team = [employee for employee in world.employees if employee.team == client.team]
    lead = person_from(team[index % len(team)].display_name)
    lead2 = person_from(team[(index + 1) % len(team)].display_name)
    project = _project_for(world, client, index)
    numbers = draw_numbers(rng)
    party = client_party(client)
    organisation = world.organisation
    return {
        language: {
            **number_slots(numbers, language),
            **party_slots(party, language),
            **staff_slots(lead, lead2, organisation.domain, language),
            **firm_slots(organisation, language),
            **project_slots(project),
        }
        for language in LANGUAGES
    }


def render_source(template_dir: str, name: str, project: Project) -> str:
    template = (CONTENT / "code" / template_dir / f"{name}.tmpl").read_text(encoding="utf-8")
    return (
        template.replace("@@PROJECT@@", project.name)
        .replace("@@CODE@@", project.code)
        .replace("@@SLUG@@", project.name.lower())
    )


def source_file_name(doc_id: str, name: str) -> str:
    """Python sources get a `.txt` suffix on disk so that linters leave the data alone."""
    return f"{doc_id}-{name}.txt" if name.endswith(".py") else f"{doc_id}-{name}"


def _source_documents(world: World) -> list[Document]:
    documents = []
    for number, (name, project_name) in enumerate(SOURCE_PLAN, 1):
        project = next(project for project in world.projects if project.name == project_name)
        doc_id = f"source-{number:02d}"
        documents.append(
            Document(
                id=doc_id,
                title=f"{project.name}: {name}",
                kind="source",
                category="SOURCE_CODE",
                language="en",
                client=None,
                text=render_source("corpus", name, project),
                entities=(project.code,),
                file=source_file_name(doc_id, name),
            )
        )
    return documents


def build_corpus(world: World) -> list[Document]:
    documents = []
    for kind, count, sections in PROSE_PLAN:
        for language in LANGUAGES:
            library = load_library(f"corpus/{kind}.{language}")
            other: Language = "en" if language == "el" else "el"
            for index, client in enumerate(key_accounts(world, language)[:count]):
                rng = Random(f"{world.seed}:corpus:{kind}:{language}:{index}")
                slots = document_slots(world, client, index, rng)
                documents.append(
                    compose(
                        library,
                        f"{kind}-{language}-{index + 1:02d}",
                        slots[language],
                        slots[other],
                        rng,
                        sections=sections,
                        title=index,
                        client=client.id,
                    )
                )
    return documents + _source_documents(world)
