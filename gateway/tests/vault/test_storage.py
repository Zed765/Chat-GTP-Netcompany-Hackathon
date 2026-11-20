"""What the vault leaves in Redis, and for how long."""

import base64
import re
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from redis.asyncio.client import Pipeline
from redis.exceptions import ConnectionError as RedisConnectionError

from gateway.app.core.deps import Deps
from gateway.app.core.textnorm import entity_key, fold
from gateway.app.core.types import RehydrationReport
from gateway.app.vault import VaultService, build
from gateway.app.vault.sealing import Sealer
from gateway.tests.conftest import TEST_REDIS
from gateway.tests.vault.helpers import CONVERSATION, TTL_SECONDS, VAULT_KEY, found

TEXT = (
    "Η Μαρία Παπαδοπούλου (maria@helios.example, ΑΦΜ 123456789) of Helios Shipping SA "
    "uses key sk-test-abcd1234 and IBAN GR1601101250000000012300695."
)
ENTITIES = {
    "Μαρία Παπαδοπούλου": "PERSON",
    "maria@helios.example": "EMAIL",
    "123456789": "AFM",
    "Helios Shipping SA": "CLIENT",
    "sk-test-abcd1234": "SECRET",
    "GR1601101250000000012300695": "IBAN",
}
STORED = {surface: data_type for surface, data_type in ENTITIES.items() if data_type != "SECRET"}

KEY_NAME = re.compile(r"aspida:vault:\{[0-9a-f]{32}\}:(links|values)")
LINK_FIELD = re.compile(r"[0-9a-f]{32}")
LINK_VALUE = re.compile(r"\d+|<[A-Z]+_\d+>( <[A-Z]+_\d+>)*")


async def names(redis: Redis, pattern: str = "*") -> list[str]:
    return sorted(str(key) for key in await redis.keys(pattern))


async def hashes(redis: Redis, kind: str) -> list[dict[str, str]]:
    return [
        {str(field): str(value) for field, value in (await redis.hgetall(key)).items()}
        for key in await names(redis, f"*:{kind}")
    ]


async def lifetimes(redis: Redis) -> list[int]:
    return [await redis.ttl(key) for key in await names(redis)]


async def keys_of(vault: VaultService, redis: Redis, conversation: str) -> dict[str, str]:
    """The names of a conversation's hashes, found by letting the vault create them."""
    before = set(await names(redis))
    await vault.mask(conversation, "AFM 123456789", found("AFM 123456789", ENTITIES))
    created = set(await names(redis)) - before
    await redis.delete(*created)
    return {key.rsplit(":", 1)[1]: key for key in created}


async def test_no_value_appears_in_the_masked_text(vault: VaultService) -> None:
    result = await vault.mask(CONVERSATION, TEXT, found(TEXT, ENTITIES))
    assert len(result.spans) == len(ENTITIES)
    for value in ENTITIES:
        assert value not in result.text


async def test_redis_holds_only_keyed_hashes_placeholders_and_ciphertext(
    vault: VaultService, redis: Redis
) -> None:
    await vault.mask(CONVERSATION, TEXT, found(TEXT, ENTITIES))

    assert all(KEY_NAME.fullmatch(key) for key in await names(redis))
    (links,) = await hashes(redis, "links")
    assert all(LINK_FIELD.fullmatch(field) for field in links)
    assert all(LINK_VALUE.fullmatch(value) for value in links.values())

    (values,) = await hashes(redis, "values")
    assert sorted(values) == ["<AFM_1>", "<CLIENT_1>", "<EMAIL_1>", "<IBAN_1>", "<PERSON_1>"]
    ciphertext = b"".join(base64.b64decode(sealed) for sealed in values.values())
    for value in ENTITIES:
        forms = {value, fold(value), entity_key(value), *value.split(), *entity_key(value).split()}
        for form in forms:
            assert len(form) < 4 or form.encode() not in ciphertext, form


async def test_a_secret_leaves_no_trace_in_redis(vault: VaultService, redis: Redis) -> None:
    await vault.mask("with:secret", TEXT, found(TEXT, ENTITIES))
    await vault.mask("without:secret", TEXT, found(TEXT, STORED))

    with_secret, without_secret = await hashes(redis, "links")
    assert len(with_secret) == len(without_secret)
    for values in await hashes(redis, "values"):
        assert len(values) == len(STORED)
    assert all(info.data_type != "SECRET" for info in await vault.describe("with:secret"))


async def test_keys_are_safe_whatever_the_client_put_in_the_conversation_id(
    vault: VaultService, redis: Redis
) -> None:
    awkward = "0123456789abcdef:" + "a b:c{d}*?[e]\n\x00é" * 4
    await vault.mask(awkward, TEXT, found(TEXT, ENTITIES))

    links, values = sorted(await names(redis))

    assert KEY_NAME.fullmatch(links) and KEY_NAME.fullmatch(values)
    assert links.removesuffix(":links") == values.removesuffix(":values")
    assert (await vault.resolve(awkward, "<AFM_1>"))[0] == "123456789"
    assert (await vault.resolve(awkward[:-1], "<AFM_1>"))[0] == "<AFM_1>"


async def test_each_value_is_sealed_under_a_fresh_nonce(vault: VaultService, redis: Redis) -> None:
    for conversation in ("a:1", "a:2"):
        await vault.mask(conversation, "AFM 123456789", found("AFM 123456789", ENTITIES))

    sealed = [values["<AFM_1>"] for values in await hashes(redis, "values")]

    assert len({base64.b64decode(value)[:12] for value in sealed}) == 2
    assert len({base64.b64decode(value)[12:] for value in sealed}) == 2


async def test_both_hashes_expire_and_every_use_renews_them(
    vault: VaultService, redis: Redis
) -> None:
    async def about_to_expire() -> None:
        for key in await names(redis):
            await redis.expire(key, 60)

    await vault.mask(CONVERSATION, TEXT, found(TEXT, ENTITIES))
    assert await lifetimes(redis) == [TTL_SECONDS, TTL_SECONDS]

    await about_to_expire()
    await vault.mask(CONVERSATION, "AFM 123456789", found("AFM 123456789", ENTITIES))
    assert await lifetimes(redis) == [TTL_SECONDS, TTL_SECONDS]

    await about_to_expire()
    await vault.rehydrator(CONVERSATION, ["<AFM_1>"])
    assert await lifetimes(redis) == [TTL_SECONDS, TTL_SECONDS]

    await about_to_expire()
    await vault.resolve(CONVERSATION, "<AFM_1>")
    assert await lifetimes(redis) == [TTL_SECONDS, TTL_SECONDS]


async def test_end_deletes_everything_the_conversation_held(
    vault: VaultService, redis: Redis
) -> None:
    await vault.mask(CONVERSATION, TEXT, found(TEXT, ENTITIES))
    await vault.mask("someone:else", TEXT, found(TEXT, ENTITIES))

    await vault.end(CONVERSATION)

    assert len(await names(redis)) == 2
    assert await vault.describe(CONVERSATION) == []
    assert await vault.resolve(CONVERSATION, "<PERSON_1>") == (
        "<PERSON_1>",
        RehydrationReport(sent=0, returned=0, unresolved=("<PERSON_1>",)),
    )
    assert (await vault.resolve("someone:else", "<AFM_1>"))[0] == "123456789"

    await vault.end("someone:else")
    await vault.end("never:used")
    assert await names(redis) == []


async def test_a_wrong_key_cannot_read_the_vault(vault: VaultService, redis: Redis) -> None:
    masked = await vault.mask(CONVERSATION, TEXT, found(TEXT, ENTITIES))
    (stolen,) = await names(redis, "*:values")
    intruder = VaultService(redis, b"x" * 32, TTL_SECONDS)
    await redis.copy(stolen, (await keys_of(intruder, redis, CONVERSATION))["values"])

    restored, report = await intruder.resolve(CONVERSATION, masked.text)

    assert restored == masked.text
    assert report.returned == 0
    assert sorted(report.unresolved) == sorted(await redis.hkeys(stolen))


async def test_values_copied_into_another_conversation_do_not_open(
    vault: VaultService, redis: Redis
) -> None:
    await vault.mask(CONVERSATION, TEXT, found(TEXT, ENTITIES))
    (stolen,) = await names(redis, "*:values")
    await redis.copy(stolen, (await keys_of(vault, redis, "fedcba9876543210:thief"))["values"])

    restored, report = await vault.resolve("fedcba9876543210:thief", "<PERSON_1> <AFM_1>")

    assert restored == "<PERSON_1> <AFM_1>"
    assert report.unresolved == ("<PERSON_1>", "<AFM_1>")


def test_a_sealed_value_opens_only_with_its_key_conversation_and_placeholder() -> None:
    sealer = Sealer(VAULT_KEY)
    sealed = sealer.seal("conversation", "<AFM_1>", "123456789")

    assert sealer.open("conversation", "<AFM_1>", sealed) == "123456789"
    assert sealer.open("other", "<AFM_1>", sealed) is None
    assert sealer.open("conversation", "<AFM_2>", sealed) is None
    assert Sealer(b"x" * 32).open("conversation", "<AFM_1>", sealed) is None
    assert sealer.open("conversation", "<AFM_1>", sealed[:-4] + "AAAA") is None
    assert sealer.open("conversation", "<AFM_1>", "not base64!") is None


def test_lookup_tokens_depend_on_the_key_and_on_every_part() -> None:
    sealer = Sealer(VAULT_KEY)
    token = sealer.token("link", "conversation", "exact", "AFM", "123456789")

    assert token == sealer.token("link", "conversation", "exact", "AFM", "123456789")
    assert LINK_FIELD.fullmatch(token)
    others = {
        sealer.token("link", "other", "exact", "AFM", "123456789"),
        sealer.token("link", "conversation", "exact", "AFM123456789"),
        sealer.token("link", "conversation", "exact", "AF", "M123456789"),
        Sealer(b"x" * 32).token("link", "conversation", "exact", "AFM", "123456789"),
    }
    assert len(others) == 4 and token not in others


async def test_masking_and_restoring_take_few_round_trips(
    vault: VaultService, monkeypatch: pytest.MonkeyPatch
) -> None:
    trips = 0
    execute = Pipeline.execute

    async def counted(self: Pipeline, raise_on_error: bool = True) -> list[object]:
        nonlocal trips
        trips += 1
        return list(await execute(self, raise_on_error))

    monkeypatch.setattr(Pipeline, "execute", counted)

    await vault.mask(CONVERSATION, TEXT, found(TEXT, ENTITIES))
    assert trips == 2
    await vault.mask(CONVERSATION, TEXT, found(TEXT, ENTITIES))
    assert trips == 3
    await vault.rehydrator(CONVERSATION, [])
    assert trips == 4
    await vault.mask(CONVERSATION, "nothing sensitive", [])
    assert trips == 4


@pytest.fixture
async def real_redis() -> AsyncIterator[tuple[Redis, str]]:
    """The test Redis server, and a key prefix no other test run uses."""
    client = Redis.from_url(TEST_REDIS, decode_responses=True)
    prefix = f"aspida-test:{uuid4().hex}"
    try:
        await client.ping()
    except RedisConnectionError:
        await client.aclose()
        pytest.skip("Redis is not running; start it with `make test-deps`")
    yield client, prefix
    leftover = [key async for key in client.scan_iter(f"{prefix}:*")]
    if leftover:
        await client.delete(*leftover)
    await client.aclose()


@pytest.mark.integration
async def test_the_vault_works_on_a_real_redis(real_redis: tuple[Redis, str]) -> None:
    redis, prefix = real_redis
    vault = VaultService(redis, VAULT_KEY, TTL_SECONDS, key_prefix=prefix)

    masked = await vault.mask(CONVERSATION, TEXT, found(TEXT, ENTITIES))
    assert await vault.mask(CONVERSATION, TEXT, found(TEXT, ENTITIES)) == masked
    assert "<PERSON_1>" in masked.text and "<SECRET_REDACTED>" in masked.text

    keys = [key async for key in redis.scan_iter(f"{prefix}:*")]
    assert len(keys) == 2
    for key in keys:
        assert TTL_SECONDS - 5 <= await redis.ttl(key) <= TTL_SECONDS

    rehydrator = await vault.rehydrator(CONVERSATION, [span.placeholder for span in masked.spans])
    restored = "".join(rehydrator.feed(char) for char in masked.text) + rehydrator.flush()
    assert restored == TEXT.replace("sk-test-abcd1234", "<SECRET_REDACTED>")
    assert rehydrator.report() == RehydrationReport(sent=5, returned=5)
    assert len(await vault.describe(CONVERSATION)) == 5

    await vault.end(CONVERSATION)
    assert [key async for key in redis.scan_iter(f"{prefix}:*")] == []


@pytest.mark.integration
async def test_build_wires_the_vault_from_the_gateway_dependencies(
    deps: Deps, redis: Redis
) -> None:
    vault = await build(deps)

    await vault.mask(CONVERSATION, TEXT, found(TEXT, ENTITIES))

    assert (await vault.resolve(CONVERSATION, "<IBAN_1>"))[0] == "GR1601101250000000012300695"
    assert await lifetimes(redis) == [deps.settings.vault_ttl_hours * 3600] * 2
