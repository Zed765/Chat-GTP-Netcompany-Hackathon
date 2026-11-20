"""T2 and T3 without a database: a stand-in store and the model double."""

import time
from collections.abc import Sequence
from types import SimpleNamespace
from typing import cast

import numpy as np
import pytest

from gateway.app.config import Settings
from gateway.app.core.deps import Deps
from gateway.app.core.types import (
    ContextualDetection,
    DataType,
    Finding,
    LocalDetection,
    RowSource,
    Tier,
    Usage,
)
from gateway.app.detect import T2_FAILED, T3_FAILED, DetectionService
from gateway.app.detect.category import CategoryVerdict
from gateway.app.detect.fingerprint import (
    DocumentInfo,
    FingerprintIndex,
    chunks,
    mask_by_type,
    normalise_category,
    reduce_placeholders,
    to_findings,
)
from gateway.app.detect.settings import DetectionSettings
from gateway.app.llm.client import Matrix
from gateway.app.protected import ProtectedData
from gateway.tests.doubles import HASH_THRESHOLDS, FakeLLM, hash_embed
from gateway.tests.protected.helpers import (
    CONTRACT,
    EXEMPLARS,
    HOLIDAY_REQUEST,
    RESEMBLES_A_CONTRACT,
    excerpt,
)

NO_FINDINGS = LocalDetection(findings=(), timings_ms={})


T3_USAGE = Usage(input_tokens=100, output_tokens=5, cost_usd=0.001)


def model(verdict: CategoryVerdict | Exception, *, delay_s: float = 0.0) -> FakeLLM:
    """A model that answers the category question with `verdict`, or fails with it."""
    return FakeLLM(answers={"CategoryVerdict": verdict}, usage=T3_USAGE, delay_s=delay_s)


class StubStore:
    def __init__(self, documents: Sequence[tuple[str, str, str, RowSource]]) -> None:
        infos: list[DocumentInfo] = []
        matrices: list[Matrix] = []
        owners: list[int] = []
        for label, category, text, source in documents:
            matrix = hash_embed(chunks(text))
            owners += [len(infos)] * len(matrix)
            infos.append(DocumentInfo(f"row-{label}", label, normalise_category(category), source))
            matrices.append(matrix)
        stacked = np.vstack(matrices) if matrices else np.zeros((0, 0), dtype=np.float32)
        self._index = FingerprintIndex(infos, stacked, owners)
        self.scopes: list[frozenset[RowSource] | None] = []

    def fingerprint_index(self, scope: frozenset[RowSource] | None = None) -> FingerprintIndex:
        self.scopes.append(scope)
        return self._index


EXEMPLAR_ROWS = [(name, category, text, RowSource.DEFAULT) for name, category, _, text in EXEMPLARS]
COMPANY_ROWS = [("MSA Zephyros", "CONTRACT", CONTRACT, RowSource.UPLOADED)]


def service(llm: FakeLLM, rows: Sequence[tuple[str, str, str, RowSource]]) -> DetectionService:
    deps = SimpleNamespace(llm=llm, settings=Settings(inline_timeout_s=0.2))
    store = cast(ProtectedData, StubStore(rows))
    return DetectionService(cast(Deps, deps), store, settings=HASH_THRESHOLDS)


def test_placeholders_reduce_to_their_type() -> None:
    masked = "Dear <PERSON_12>, the AFM <AFM_1> of <CLIENT_3> and <SECRET_REDACTED> <PERSON>"
    assert (
        reduce_placeholders(masked)
        == "Dear <PERSON>, the AFM <AFM> of <CLIENT> and <SECRET> <PERSON>"
    )
    assert reduce_placeholders("a < b and <not a placeholder>") == "a < b and <not a placeholder>"


def test_mask_by_type_skips_confidentiality_markers() -> None:
    text = "CONFIDENTIAL Maria, AFM 094014201"
    findings = [
        Finding(data_type=DataType.CONFIDENTIAL_MARKER, start=0, end=12, text="CONFIDENTIAL",
                tier=Tier.T1, score=0.9, recogniser="marker", maskable=False),
        Finding(data_type=DataType.PERSON, start=13, end=18, text="Maria", tier=Tier.T1,
                score=0.9, recogniser="ner:en"),
        Finding(data_type=DataType.AFM, start=24, end=33, text="094014201", tier=Tier.T0,
                score=0.9, recogniser="afm"),
    ]  # fmt: skip
    assert mask_by_type(text, findings) == "CONFIDENTIAL <PERSON>, AFM <AFM>"


def test_chunks_are_200_tokens_with_an_overlap_of_50() -> None:
    words = [f"w{index}" for index in range(520)]
    pieces = [piece.split() for piece in chunks(" ".join(words))]
    assert [len(piece) for piece in pieces] == [200, 200, 200, 70]
    assert pieces[1][:50] == pieces[0][150:] and pieces[3][-1] == "w519"
    assert chunks("only a few words") == ["only a few words"] and chunks("  ") == []


def test_category_names_are_normalised() -> None:
    assert [normalise_category(name) for name in ("source code", "Source-Code", " hr ")] == [
        "SOURCE_CODE", "SOURCE_CODE", "HR"
    ]  # fmt: skip


async def test_short_prompt_skips_t2() -> None:
    result = await service(FakeLLM(), COMPANY_ROWS).detect_contextual(
        "summarise the supplier clause", local=NO_FINDINGS
    )
    assert (result.categories, result.tiers_run, result.error) == ((), (), None)


async def test_excerpt_of_a_company_document_is_conclusive_and_named() -> None:
    llm = model(CategoryVerdict(category="FINANCIAL", confidence=0.9))
    detector = service(llm, [*COMPANY_ROWS, *EXEMPLAR_ROWS])
    paste = f"Can you shorten this? {excerpt(CONTRACT, 40, 120)}"
    result = await detector.detect_contextual(paste, local=NO_FINDINGS)
    (found,) = result.categories
    assert (found.category, found.tier, found.conclusive) == (DataType.CONTRACT, Tier.T2, True)
    assert found.evidence == 'matches "MSA Zephyros"'
    assert found.match is not None and found.match.source is RowSource.UPLOADED
    assert result.tiers_run == (Tier.T2,) and llm.asked == []
    assert result.timings_ms[Tier.T2] > 0 and result.usage.input_tokens > 0


async def test_same_document_masked_two_ways_scores_the_same() -> None:
    detector = service(FakeLLM(), COMPANY_ROWS)
    body = excerpt(CONTRACT, 40, 120)
    by_vault, _ = await detector.fingerprint_scores(f"<PERSON_7> of <CLIENT_2> wrote: {body}")
    by_type, _ = await detector.fingerprint_scores(f"<PERSON> of <CLIENT> wrote: {body}")
    assert by_vault is not None and by_type is not None
    assert by_vault.document is not None and by_type.document is not None
    assert by_vault.document.similarity == pytest.approx(by_type.document.similarity)


async def test_resemblance_to_exemplars_is_inconclusive_and_names_no_document() -> None:
    detector = service(FakeLLM(), EXEMPLAR_ROWS)
    result = await detector.detect_contextual(
        RESEMBLES_A_CONTRACT, local=NO_FINDINGS, use_model=False
    )
    (found,) = result.categories
    assert (found.category, found.tier, found.conclusive) == (DataType.CONTRACT, Tier.T2, False)
    assert found.evidence == "resembles a contract" and found.match is None
    assert result.tiers_run == (Tier.T2,)

    benign = await detector.detect_contextual(HOLIDAY_REQUEST, local=NO_FINDINGS)
    assert benign.categories == ()


async def test_thresholds_are_settings_the_evaluation_can_tune() -> None:
    detector = service(FakeLLM(), [*COMPANY_ROWS, *EXEMPLAR_ROWS])
    scores, _ = await detector.fingerprint_scores(f"Shorten: {excerpt(CONTRACT, 40, 120)}")
    assert scores is not None and scores.document is not None and scores.exemplars is not None
    strict = to_findings(scores, document_threshold=0.99, exemplar_threshold=0.99)
    loose = to_findings(scores, document_threshold=0.1, exemplar_threshold=0.1)
    assert strict is None and loose is not None and loose.conclusive

    detector.settings = DetectionSettings(t2_document_threshold=0.99, t2_exemplar_threshold=0.99)
    result = await detector.detect_contextual(
        f"Shorten: {excerpt(CONTRACT, 40, 120)}", local=NO_FINDINGS
    )
    assert result.categories == ()


async def test_scoped_detector_asks_the_store_for_its_layers_only() -> None:
    detector = service(FakeLLM(), EXEMPLAR_ROWS)
    scoped = detector.scoped([RowSource.DEFAULT])
    await scoped.fingerprint_scores(RESEMBLES_A_CONTRACT)
    store = cast(StubStore, scoped._protected)
    assert store.scopes == [frozenset({RowSource.DEFAULT})]


async def test_t3_confirms_a_resemblance_on_masked_text() -> None:
    llm = model(CategoryVerdict(category="CONTRACT", confidence=0.9))
    local = LocalDetection(
        findings=(
            Finding(data_type=DataType.CLIENT, start=0, end=5, text="Notos", tier=Tier.T1,
                    score=0.9, recogniser="term"),
        ),
        timings_ms={},
    )  # fmt: skip
    masked = f"<CLIENT_4> asked: {RESEMBLES_A_CONTRACT}"
    result = await service(llm, EXEMPLAR_ROWS).detect_contextual(masked, local=local)
    (found,) = result.categories
    assert (found.category, found.tier, found.conclusive) == (DataType.CONTRACT, Tier.T3, True)
    assert found.evidence == "classified as a contract"
    assert result.tiers_run == (Tier.T2, Tier.T3) and result.error is None
    assert result.usage.cost_usd == pytest.approx(0.001)
    (asked,) = llm.texts
    assert "<CLIENT> asked" in asked and "CLIENT x1" in asked and "Notos" not in asked


async def test_t3_overrules_a_resemblance_it_does_not_share() -> None:
    llm = model(CategoryVerdict(category="NONE", confidence=0.8))
    result = await service(llm, EXEMPLAR_ROWS).detect_contextual(
        RESEMBLES_A_CONTRACT, local=NO_FINDINGS
    )
    assert result.categories == () and result.tiers_run == (Tier.T2, Tier.T3)


async def test_t3_is_not_asked_when_nothing_is_inconclusive_unless_forced() -> None:
    llm = model(CategoryVerdict(category="HEALTH", confidence=0.7))
    detector = service(llm, EXEMPLAR_ROWS)
    quiet = await detector.detect_contextual(HOLIDAY_REQUEST, local=NO_FINDINGS)
    assert quiet.tiers_run == (Tier.T2,) and llm.asked == []

    forced = await detector.detect_contextual(
        "my blood test results", local=NO_FINDINGS, force_t3=True
    )
    (found,) = forced.categories
    assert (found.category, found.tier) == (DataType.HEALTH, Tier.T3)
    assert forced.tiers_run == (Tier.T3,)


@pytest.mark.parametrize(
    "llm",
    [
        model(CategoryVerdict(category="CONTRACT", confidence=0.9), delay_s=5.0),
        model(RuntimeError("upstream error")),
    ],
    ids=["timeout", "failure"],
)
async def test_t3_failure_sets_an_error_and_keeps_the_t2_finding(llm: FakeLLM) -> None:
    started = time.perf_counter()
    result = await service(llm, EXEMPLAR_ROWS).detect_contextual(
        RESEMBLES_A_CONTRACT, local=NO_FINDINGS
    )
    assert time.perf_counter() - started < 1.0
    assert result.error == T3_FAILED and result.tiers_run == (Tier.T2, Tier.T3)
    (found,) = result.categories
    assert (found.tier, found.conclusive) == (Tier.T2, False)


async def test_t2_failure_sets_an_error_instead_of_raising() -> None:
    llm = FakeLLM(embedding_error=ConnectionError("embedding service is down"))
    result = await service(llm, EXEMPLAR_ROWS).detect_contextual(
        RESEMBLES_A_CONTRACT, local=NO_FINDINGS
    )
    assert result.error == T2_FAILED and result.categories == ()
    assert result.tiers_run == (Tier.T2,)


async def test_use_model_false_never_calls_t3() -> None:
    """Importing logged prompts must not cost one model call per prompt."""
    llm = model(CategoryVerdict(category="CONTRACT", confidence=0.9))
    detector = service(llm, EXEMPLAR_ROWS)
    for variant in (detector, detector.scoped([RowSource.DEFAULT])):
        result = await variant.detect_contextual(
            RESEMBLES_A_CONTRACT, local=NO_FINDINGS, force_t3=True, use_model=False
        )
        (found,) = result.categories
        assert (found.tier, found.conclusive) == (Tier.T2, False)
        assert result.tiers_run == (Tier.T2,) and result.error is None
    assert llm.asked == []


def _outcome(result: ContextualDetection) -> tuple[object, ...]:
    return result.categories, result.tiers_run, result.error


async def test_many_texts_cost_one_embedding_request_and_agree_with_one_by_one() -> None:
    rows = [*COMPANY_ROWS, *EXEMPLAR_ROWS]
    long_texts = [
        f"Can you shorten this? {excerpt(CONTRACT, 40, 120)}",
        RESEMBLES_A_CONTRACT,
        HOLIDAY_REQUEST,
        f"<PERSON_1> asked: {RESEMBLES_A_CONTRACT}",
    ]
    texts = [long_texts[number % 4] if number % 5 else "a short prompt" for number in range(200)]

    batched_llm = FakeLLM()
    batched = await service(batched_llm, rows).detect_contextual_many(texts, use_model=False)
    (embedded,) = batched_llm.embedded
    assert len(embedded) == sum(text != "a short prompt" for text in texts)

    single = service(FakeLLM(), rows)
    one_by_one = [
        await single.detect_contextual(text, local=NO_FINDINGS, use_model=False)
        for text in texts[:10]
    ]
    assert [_outcome(result) for result in batched[:10]] == [
        _outcome(result) for result in one_by_one
    ]
    assert _outcome(batched[0]) == ((), (), None)
    assert [found.evidence for found in batched[1].categories] == ['matches "MSA Zephyros"']
    assert sum(result.usage.input_tokens for result in batched) == len(embedded)


async def test_many_short_texts_are_not_embedded_at_all() -> None:
    llm = FakeLLM()
    detector = service(llm, EXEMPLAR_ROWS)
    results = await detector.detect_contextual_many(["hello", "short one"])
    assert llm.embedded == []
    assert [_outcome(result) for result in results] == [((), (), None)] * 2
    assert await detector.detect_contextual_many([]) == []


async def test_many_texts_ask_the_model_only_when_allowed() -> None:
    texts = [RESEMBLES_A_CONTRACT, HOLIDAY_REQUEST, "short"]
    quiet_llm = model(CategoryVerdict(category="CONTRACT", confidence=0.9))
    scoped = service(quiet_llm, EXEMPLAR_ROWS).scoped([RowSource.DEFAULT])
    quiet = await scoped.detect_contextual_many(texts, use_model=False)
    assert quiet_llm.asked == []
    assert [result.tiers_run for result in quiet] == [(Tier.T2,), (Tier.T2,), ()]
    assert [found.tier for found in quiet[0].categories] == [Tier.T2]

    asking_llm = model(CategoryVerdict(category="CONTRACT", confidence=0.9))
    asked = await service(asking_llm, EXEMPLAR_ROWS).detect_contextual_many(texts)
    assert len(asking_llm.asked) == 1
    assert [found.tier for found in asked[0].categories] == [Tier.T3]


async def test_a_failed_embedding_request_marks_every_judged_text() -> None:
    llm = FakeLLM(embedding_error=ConnectionError("embedding service is down"))
    results = await service(llm, EXEMPLAR_ROWS).detect_contextual_many(
        [RESEMBLES_A_CONTRACT, "short", HOLIDAY_REQUEST]
    )
    assert [result.error for result in results] == [T2_FAILED, None, T2_FAILED]
    assert [result.tiers_run for result in results] == [(Tier.T2,), (), (Tier.T2,)]
