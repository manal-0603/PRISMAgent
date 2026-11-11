"""Unit tests of the deterministic components (no network, no LLM)."""

from __future__ import annotations

import math

import pytest

from sysrev.agents.critic import uncited_ratio
from sysrev.agents.extraction import _normalise, _overall, verify_quote
from sysrev.agents.synthesis import number_citations
from sysrev.llm import RateLimiter, extract_json
from sysrev.models import DomainJudgement, Record
from sysrev.sources.connectors import _abstract_from_inverted_index, _openalex_filter, norm_doi
from sysrev.tools import stats
from sysrev.tools.dedup import deduplicate, norm_title
from sysrev.tools.export import bibtex_key, format_reference, md_table, to_bibtex
from sysrev.tools.prisma import PRISMA_2020_ITEMS, PrismaFlow, split_sections, validate_checklist


# --------------------------------------------------------------------------- #
# De-duplication
# --------------------------------------------------------------------------- #


def test_dedup_by_doi_merges_sources_and_keeps_longest_abstract():
    a = Record(title="Deep learning for screening", doi="10.1/abc", abstract="short", sources=["pubmed"])
    b = Record(title="Deep Learning for Screening.", doi="10.1/abc", abstract="a much longer abstract", pmid="42", sources=["openalex"])
    unique, log = deduplicate([a, b])
    assert len(unique) == 1 and log[0]["reason"] == "doi"
    assert unique[0].sources == ["openalex", "pubmed"]
    assert unique[0].abstract == "a much longer abstract" and unique[0].pmid == "42"
    assert unique[0].rid == "R0001"


def test_dedup_fuzzy_title_requires_close_years():
    title = "Effect of exercise on depression in older adults: a randomised trial"
    a = Record(title=title, year=2020, sources=["pubmed"])
    b = Record(title=title.replace("randomised", "randomized"), year=2021, sources=["arxiv"])
    c = Record(title=title.replace("randomised", "randomized"), year=2012, sources=["openalex"])
    unique, log = deduplicate([a, b, c])
    assert len(unique) == 2
    assert [entry["reason"] for entry in log] == ["title_fuzzy"]


def test_dedup_keeps_distinct_records():
    records = [Record(title=f"A completely different study number {i} about topic {i * 7}", sources=["x"]) for i in range(5)]
    unique, log = deduplicate(records)
    assert len(unique) == 5 and not log
    assert [r.rid for r in unique] == ["R0001", "R0002", "R0003", "R0004", "R0005"]


def test_dedup_prefers_journal_doi_over_arxiv_doi():
    preprint = Record(title="Transformers for abstract screening in reviews", doi="10.48550/arxiv.2301.00001", arxiv_id="2301.00001", sources=["arxiv"])
    journal = Record(title="Transformers for abstract screening in reviews", doi="10.1000/j.1", sources=["openalex"])
    unique, _ = deduplicate([preprint, journal])
    assert len(unique) == 1 and unique[0].doi == "10.1000/j.1" and unique[0].arxiv_id == "2301.00001"


def test_norm_title_and_doi():
    assert norm_title("  Café-au-lait: A Study!  ") == "cafe au lait a study"
    assert norm_doi("https://doi.org/10.1000/ABC") == "10.1000/abc"
    assert norm_doi("doi: 10.1/x") == "10.1/x"
    assert norm_doi(None) is None


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #


def test_cohen_kappa_known_value():
    # 2x2 table: both yes 20, both no 15, A yes/B no 5, A no/B yes 10 -> kappa = 0.4
    a = ["y"] * 20 + ["n"] * 15 + ["y"] * 5 + ["n"] * 10
    b = ["y"] * 20 + ["n"] * 15 + ["n"] * 5 + ["y"] * 10
    assert stats.cohen_kappa(a, b) == pytest.approx(0.4, abs=1e-9)
    assert stats.kappa_label(0.4) == "fair"


def test_cohen_kappa_edge_cases():
    assert stats.cohen_kappa([], []) is None
    assert stats.cohen_kappa(["y", "y"], ["y", "y"]) is None  # no variance: undefined
    assert stats.cohen_kappa(["y", "n"], ["y", "n"]) == pytest.approx(1.0)


def test_classification_metrics():
    predicted = [True, True, True, False, False, False, False, False]
    truth = [True, True, False, True, False, False, False, False]
    m = stats.classification_metrics(predicted, truth)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (2, 1, 1, 4)
    assert m["recall_sensitivity"] == pytest.approx(2 / 3, abs=1e-4)
    assert m["precision"] == pytest.approx(2 / 3, abs=1e-4)
    assert m["specificity"] == pytest.approx(0.8)
    assert m["work_saved_over_sampling"] == pytest.approx(5 / 8 - (1 - 2 / 3), abs=1e-4)


def test_random_effects_pooling_matches_hand_calculation():
    # Two log odds ratios with equal variance: pooled = mean; Q = (d^2)/(2 v)
    effects = [stats.StudyEffect("a", math.log(2.0), 0.2), stats.StudyEffect("b", math.log(4.0), 0.2)]
    pooled = stats.pool(effects, log_scale=True)
    assert pooled.fixed == pytest.approx((math.log(2) + math.log(4)) / 2)
    q = (math.log(4) - math.log(2)) ** 2 / (2 * 0.04)
    assert pooled.q == pytest.approx(q)
    assert pooled.tau2 == pytest.approx((q - 1) / (2 / 0.04 - (2 / 0.04**2) / (2 / 0.04)))
    assert pooled.as_dict()["random_effects"] == pytest.approx(math.sqrt(8), abs=1e-3)
    assert pooled.i2 == pytest.approx((q - 1) / q * 100)


def test_pool_homogeneous_studies_has_zero_heterogeneity():
    effects = [stats.StudyEffect(str(i), 0.5, 0.1) for i in range(4)]
    pooled = stats.pool(effects)
    assert pooled.tau2 == 0 and pooled.i2 == 0
    assert pooled.random == pytest.approx(0.5)
    assert pooled.random_ci[1] - pooled.random_ci[0] == pytest.approx(2 * stats.Z95 * 0.05)
    assert stats.pool(effects[:1]) is None


def test_effect_from_ci():
    estimate, se = stats.effect_from_ci(2.0, 1.0, 4.0, "OR")
    assert estimate == pytest.approx(math.log(2)) and se == pytest.approx(math.log(4) / (2 * stats.Z95))
    estimate, se = stats.effect_from_ci(0.5, 0.3, 0.7, "MD")
    assert estimate == 0.5 and se == pytest.approx(0.4 / (2 * stats.Z95))
    assert stats.effect_from_ci(-1, 0.5, 2, "RR") is None
    assert stats.effect_from_ci(1, 1, 1, "MD") is None


# --------------------------------------------------------------------------- #
# PRISMA
# --------------------------------------------------------------------------- #


def _flow() -> PrismaFlow:
    return PrismaFlow(
        identified={"pubmed": 120, "arxiv": 80}, duplicates_removed=30, removed_by_automation=20,
        records_screened=150, records_excluded=110, reports_sought=40, reports_not_retrieved=2,
        reports_assessed=38, assessed_on_abstract_only=5, reports_excluded={"E1": 20, "E2": 6}, studies_included=12,
    )


def test_prisma_flow_consistency():
    flow = _flow()
    assert flow.identified_total == 200 and flow.check() == []
    flow.studies_included = 13
    assert len(flow.check()) == 1 and "included" in flow.check()[0]
    flow.records_screened = 151
    assert len(flow.check()) == 3


def test_prisma_flow_renders(tmp_path):
    flow = _flow()
    mermaid = flow.to_mermaid()
    assert mermaid.startswith("flowchart TD") and "n = 12" in mermaid and "n = 200" in mermaid
    png = flow.to_png(tmp_path / "flow.png")
    assert png.exists() and png.stat().st_size > 10_000


def test_prisma_checklist_has_all_27_items():
    numbers = {int("".join(ch for ch in item["id"] if ch.isdigit())) for item in PRISMA_2020_ITEMS}
    assert numbers == set(range(1, 28))
    assert len(PRISMA_2020_ITEMS) == 42


def test_checklist_validator_detects_missing_sections():
    filler = " ".join(["word"] * 15)
    full = "# Effects of X: a systematic review\n\n## Abstract\n" + filler
    for item in PRISMA_2020_ITEMS[2:]:
        for section in item["sections"]:
            full += f"\n\n### {section}\n{filler}"
    rows = validate_checklist(full)
    assert all(row["reported"] for row in rows)

    without_title_type = full.replace("a systematic review", "a study")
    assert not validate_checklist(without_title_type)[0]["reported"]

    thin = full.replace(f"### 2.8 Effect measures\n{filler}", "### 2.8 Effect measures\nToo short.")
    missing = [row["item"] for row in validate_checklist(thin) if not row["reported"]]
    assert missing == ["12"]


def test_split_sections():
    sections = split_sections("# Title here\n\n## A\ntext a\n\n### A.1\ntext a1")
    assert sections["TITLE"] == "Title here" and sections["A"] == "text a" and sections["A.1"] == "text a1"


# --------------------------------------------------------------------------- #
# Citations, quotes, appraisal rules
# --------------------------------------------------------------------------- #


def test_number_citations():
    records = {rid: Record(rid=rid, title=rid) for rid in ("R0001", "R0002", "R0003")}
    text = "First [R0002]. Then [R0001; R0002] and [R0003, R0009]. Passage label [R0001:fulltext:4]. Ghost [R0042]."
    out, order, unknown = number_citations(text, records)
    assert order == ["R0002", "R0001", "R0003"]
    assert unknown == ["R0009", "R0042"]
    assert out == "First [1]. Then [1, 2] and [3]. Passage label [2]. Ghost ."


def test_number_citations_tolerates_model_habits():
    records = {rid: Record(rid=rid, title=rid) for rid in ("R0001", "R0002", "R0003")}
    out, order, unknown = number_citations("CJK【R0002】【R0001】. Parens (R0003; R0001). Bare R0002 here. | Smith [R0003] |", records)
    assert order == ["R0002", "R0001", "R0003"] and unknown == []
    assert out == "CJK[1, 2]. Parens [2, 3]. Bare [1] here. | Smith [3] |"


def test_verify_quote():
    source = _normalise("We enrolled 312 patients (mean age 54.2 years). Sensitivity was 91.5% (95% CI 88–94).")
    assert verify_quote("We enrolled 312 patients (mean age 54.2 years).", source) is True
    assert verify_quote("we  enrolled 312 patients\n(mean age 54.2 years)", source) is True  # whitespace / case
    assert verify_quote("We enrolled 450 participants across twelve hospital sites in Asia.", source) is False
    assert verify_quote("", source) is None and verify_quote("n/a", source) is None


def test_overall_risk_of_bias_rule():
    def judge(*levels: str) -> str:
        return _overall([DomainJudgement(domain=str(i), judgement=lv, justification="") for i, lv in enumerate(levels)])

    assert judge("low", "low") == "low"
    assert judge("low", "some concerns") == "some concerns"
    assert judge("low", "unclear") == "some concerns"
    assert judge("unclear", "unclear") == "unclear"
    assert judge("low", "high", "unclear") == "high"


def test_uncited_ratio():
    text = "Accuracy was high in three large studies [R0001]. This sentence has no citation at all here. Short one."
    assert uncited_ratio(text) == pytest.approx(0.5)
    assert uncited_ratio("") == 0.0


# --------------------------------------------------------------------------- #
# LLM plumbing, connectors, export
# --------------------------------------------------------------------------- #


def test_extract_json_strips_reasoning_and_fences():
    assert extract_json('<think>hmm {"a": 0}</think>```json\n{"a": 1}\n```') == '{"a": 1}'
    assert extract_json('Here you go: {"a": {"b": 2}} done') == '{"a": {"b": 2}}'


def test_rate_limiter_accounts_tokens():
    limiter = RateLimiter(tokens_per_minute=1000, requests_per_minute=10)
    assert limiter.acquire(400) == 0.0
    assert limiter.acquire(500) == 0.0
    limiter.correct(500, 100)  # the second call really used 100 tokens
    assert sum(n for _, n in limiter._events) == 500
    assert limiter.acquire(450) == 0.0  # fits only thanks to the correction


def test_openalex_helpers():
    assert _abstract_from_inverted_index({"world": [1], "Hello": [0], "again": [2]}) == "Hello world again"
    assert _abstract_from_inverted_index(None) == ""
    assert _openalex_filter('("a" OR "b") || 2018-2024') == {
        "filter": 'title_and_abstract.search:("a" OR "b"),from_publication_date:2018-01-01,to_publication_date:2024-12-31'
    }
    assert _openalex_filter("plain, query") == {"filter": "title_and_abstract.search:plain  query"}


def test_bibtex_and_reference():
    rec = Record(rid="R0007", title="Machine learning & screening", authors=["Smith, Jane", "Doe, John"], year=2023,
                 venue="J Test", doi="10.1/x")
    assert bibtex_key(rec) == "smith2023machine"
    bib = to_bibtex([rec, rec])
    assert "@article{smith2023machine," in bib and "@article{smith2023machineb," in bib and "\\&" in bib
    assert format_reference(rec) == "Smith J, Doe J. Machine learning & screening. J Test. 2023. https://doi.org/10.1/x"
    assert rec.short_ref() == "Smith et al. (2023)"


def test_author_name_normalisation():
    from sysrev.sources.connectors import initials_last, last_first
    from sysrev.tools.export import vancouver_name

    assert last_first("Jane A. Smith") == "Smith, Jane A."
    assert last_first("Rens van de Schoot") == "van de Schoot, Rens"
    assert last_first("Smith, Jane") == "Smith, Jane" and last_first("Plato") == "Plato"
    assert initials_last("Hilkenmeier F") == "Hilkenmeier, F"
    assert initials_last("van der Waal JM") == "van der Waal, JM"
    assert initials_last("Consortium Name") == "Consortium Name"
    assert vancouver_name("Smith, Jane Ann") == "Smith JA" and vancouver_name("Hilkenmeier, F") == "Hilkenmeier F"
    assert vancouver_name("van de Schoot, Rens") == "van de Schoot R" and vancouver_name("WHO") == "WHO"
    assert Record(title="t", authors=["Hilkenmeier, F"], year=2026).short_ref() == "Hilkenmeier (2026)"


def test_md_table_escapes_pipes():
    table = md_table([{"a": "x|y", "b": None}])
    assert table.splitlines()[2] == "| x/y | - |"


def test_markdown_to_docx(tmp_path):
    from docx import Document

    from sysrev.tools.export import markdown_to_docx

    md = "# Title\n\n## Section\n\nSome **bold** text.\n\n- item one\n- item two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    path = markdown_to_docx(md, tmp_path / "out.docx")
    doc = Document(str(path))
    assert [p.text for p in doc.paragraphs if p.text][:3] == ["Title", "Section", "Some bold text."]
    assert doc.tables[0].cell(1, 1).text == "2"


def test_scrub_removes_account_identifiers():
    from sysrev.llm import scrub

    message = "Rate limit reached in organization `org_01abcDEF234xyz` for key gsk_abcdefgh12345678 on tokens per day"
    assert scrub(message) == "Rate limit reached in organization `org_<redacted>` for key <redacted-key> on tokens per day"
    # ordinary words that merely contain "sk_" or "org_" must survive (this once corrupted exported JSON keys)
    harmless = '{"risk_of_bias_approach": "x", "task_models": {}, "reorg_plan": 1, "ask-me-anything-about-this": 2}'
    assert scrub(harmless) == harmless


def test_guard_blocks_exclusions_resting_only_on_full_text_criteria():
    from sysrev.agents.screening import guard_exclusion
    from sysrev.models import ReviewerVote

    locked = {"I2", "E3"}

    def vote(decision: str, criteria: list[str]) -> ReviewerVote:
        return ReviewerVote(decision=decision, criteria=criteria, rationale="no comparator mentioned", confidence=0.8)

    blocked, fired = guard_exclusion(vote("exclude", ["E3"]), locked)
    assert fired and blocked.decision == "unsure" and blocked.criteria == ["E3"]
    assert blocked.rationale.startswith("[Exclusion not allowed at this stage: E3") and "no comparator mentioned" in blocked.rationale
    assert guard_exclusion(vote("exclude", ["E3", "I2"]), locked)[1] is True
    # at least one criterion an abstract can settle: the exclusion stands
    kept, fired = guard_exclusion(vote("exclude", ["E1", "E3"]), locked)
    assert not fired and kept.decision == "exclude"
    # nothing to check against, or not an exclusion: untouched
    assert guard_exclusion(vote("exclude", []), locked) == (vote("exclude", []), False)
    assert guard_exclusion(vote("include", ["E3"]), locked)[1] is False
    assert guard_exclusion(vote("exclude", ["E3"]), set())[1] is False


def test_protocol_marks_full_text_only_criteria():
    from sysrev.agents.planner import _apply_fixed, full_text_only_ids, protocol_brief
    from sysrev.models import Criterion, Protocol

    protocol = Protocol(
        title="T: a systematic review", research_question="q", rationale="r", objectives=["o"], framework="PICO",
        framework_elements={"P": "p"}, study_designs=["cohort"], databases=["pubmed"], outcomes=["x"], data_items=["item"],
        risk_of_bias_approach="rob", synthesis_plan="narrative",
        inclusion_criteria=[Criterion(id="a", text="Patients with condition X"),
                            Criterion(id="b", text="Study includes a control group", full_text_only=True)],
        exclusion_criteria=[Criterion(id="c", text="Editorials and reviews")],
    )
    fixed = _apply_fixed(protocol, {"exclusion_criteria": ["Animal studies"]})
    assert [(c.id, c.full_text_only) for c in fixed.inclusion_criteria] == [("I1", False), ("I2", True)]
    assert [(c.id, c.text, c.full_text_only) for c in fixed.exclusion_criteria] == [
        ("E1", "Editorials and reviews", False), ("E2", "Animal studies", False)]
    assert full_text_only_ids(fixed) == {"I2"}
    plain, marked = protocol_brief(fixed), protocol_brief(fixed, mark_full_text_only=True)
    assert "[full text only]" not in plain and "  I2. Study includes a control group" in plain
    assert "  I2. [full text only] Study includes a control group" in marked and "  I1. Patients with condition X" in marked
    # a protocol written before this field existed loads with the safeguard off
    assert Criterion.model_validate({"id": "I1", "text": "old"}).full_text_only is False
