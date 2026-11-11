# Technical report — an agentic AI pipeline for systematic reviews

## 1. Objective

Design, implement and evaluate an autonomous multi-agent system that conducts a systematic
literature review end to end from a research question, following PRISMA 2020, with transparent
and reproducible execution and human oversight at the critical decision points.

The requirements of the project statement and where each is met:

| Requirement | Where |
|---|---|
| Modular multi-agent architecture with LangChain / LangGraph | `src/sysrev/graph.py`, `src/sysrev/agents/` (section 2) |
| RAG over scientific corpora (PubMed, Semantic Scholar, arXiv, OpenAlex…) | `src/sysrev/sources/`, `src/sysrev/rag/index.py` (section 3) |
| Full PRISMA workflow: protocol, search, dual screening, extraction, risk of bias, synthesis, report | sections 2 and 4 |
| Transparency: logging, citation tracking, decision rationales, execution traces | section 5 |
| Human-in-the-loop at critical decision points | section 2.3 |
| General purpose, minimal configuration | one command, one API key; `config/protocol_template.yaml` |
| Configurable PRISMA-aligned protocol template | `config/protocol_template.yaml` |
| End-to-end demonstration on a real topic | `examples/demo_run/` (section 6) |
| Evaluation: completeness, accuracy, inter-agent consistency, time savings | section 7 |

## 2. Architecture

### 2.1 Orchestration

The workflow is a LangGraph `StateGraph` with a hub-and-spoke shape: a **coordinator** node routes
to twelve stage nodes, and every stage returns to the coordinator.

```
protocol → search_strategy → [human 1] → retrieval → screen_title_abstract → [human 2]
→ screen_full_text → extraction → synthesis ⇄ critic → [human 3] → finalize
```

Design decisions:

- **Small state, artifacts on disk.** The graph state holds only the run id, the list of completed
  stages, pending feedback and headline numbers. Records, decisions and extractions live in the run
  directory as typed JSON (Pydantic models in `models.py`). The state stays cheap to checkpoint,
  and the artifacts are the audit trail.
- **Checkpointing.** A SQLite checkpointer saves the state after every node. A run can stop for
  human review, hit a quota, or crash, and `sysrev resume` continues from the same point — in a
  new process if needed. This is tested (`tests/test_graph.py`).
- **Loops.** Completing a stage adds it to `done`; a loop removes stages from `done`. The human can
  send the protocol back (planner and search agent rerun, protocol versioned), the critic can send
  the manuscript back to the writer (bounded by `--qa-rounds`), and the human can request one more
  revision at the last checkpoint.
- **The planner briefs the other agents.** Besides the protocol, the planner writes a short,
  topic-specific brief per stage (typical false positives, ambiguous terms, hard-to-find data
  items). Each agent's prompt includes its brief, so the decomposition is more than routing.

### 2.2 Agents

| Agent | Input | Output | Notes |
|---|---|---|---|
| Planner | question, protocol template | `protocol_vN.json`, `plan_vN.json` | Template constraints are enforced in code after generation, not left to the model |
| Search Strategy | protocol | `search_strategy_vN.json` | Tool-calling loop: writes a query, calls `test_query(database, query)` against the live API, reads the hit count, refines. Every tested query is logged. A deterministic query builder is the fallback |
| Retrieval | queries | `records_raw.jsonl`, `records.jsonl`, `dedup_log.jsonl`, index | No LLM. De-duplication cascade: DOI, PMID, arXiv id, exact title, fuzzy title (≥95%, years ≤1 apart, same numbers) |
| Screening | protocol, records | `screening_*.jsonl`, `agreement_*.json` | Two reviewers on different models, never shown each other's votes; adjudicator sees both rationales. Title/abstract: only positive evidence of ineligibility excludes |
| Extraction and Appraisal | included studies, index | `extractions.jsonl`, `risk_of_bias.jsonl` | Every value needs a verbatim quotation; code checks the quotation exists in the source. Overall risk of bias is derived by rule from the domain judgements |
| Synthesis and Writing | all artifacts | `report_draft.md`, `themes`, `meta_analysis`, `evidence_map.png` | Process facts (methods, counts, tables, references) are rendered by code; the model writes only interpretation, with a citation after every claim |
| Critic / QA | draft, artifacts | `qa_report_vN.json` | Rule-based checks plus LLM audits on a different model from the writer |

### 2.3 Human-in-the-loop

Three checkpoints use LangGraph `interrupt()`:

1. **Protocol and search strategy** — approve, edit, or request changes in free text.
2. **Title/abstract decisions** — approve or override individual decisions.
3. **Manuscript** — approve or request a revision.

In autonomous mode (`--auto`) the checkpoints are auto-approved and the manuscript states that no
human verified the decisions. Human overrides are logged with the previous value.

### 2.4 LLM layer

`llm.py` is shared by all agents:

- **Provider-agnostic** factory (Groq by default; Ollama, Anthropic, OpenAI optional).
- **Task → model mapping** in configuration. Three models are used so that the two screening
  reviewers are different models, the critic differs from the writer, and the load is spread over
  three independent quota buckets.
- **Token-aware rate limiter** (sliding 60-second window per model) and back-off on HTTP 429.
- **Daily quota handling**: a wait longer than five minutes is treated as quota exhaustion; the
  stage stops instead of degrading results, and the run is resumable.
- **Structured output**: the schema is rendered compactly in the prompt, the reply is validated
  with Pydantic, and invalid replies are returned to the model with the validation error.
- **Deterministic cache** on disk keyed by model, prompt and schema; temperature 0.
- **Tracing** of every call (prompt, response, tokens, latency) to `llm_trace.jsonl`.

## 3. Retrieval-augmented generation

| Step | Implementation |
|---|---|
| Sources | PubMed (E-utilities), Europe PMC, OpenAlex, arXiv, Semantic Scholar — one interface, no key required |
| Full text | Europe PMC JATS XML (tables rendered row by row, formulas' LaTeX removed), arXiv PDF, open-access publisher PDF (PyMuPDF) |
| Chunking | recursive splitter, 1,100 characters, 150 overlap, section heading attached to each chunk |
| Dense retrieval | `BAAI/bge-small-en-v1.5` (local ONNX) in Chroma, cosine |
| Sparse retrieval | BM25 (`rank-bm25`) |
| Fusion | reciprocal rank fusion (k = 60) |
| Re-ranking | FlashRank cross-encoder `ms-marco-MiniLM-L-12-v2` |
| Compression | sentence-level filter by embedding similarity to the query, sentences kept verbatim |

Where RAG is used:

1. **Prioritisation** — when more records are retrieved than the screening budget, they are ranked
   against the review question and the top ones kept; the others are reported in the PRISMA diagram
   as removed by automation tools.
2. **Full-text screening** — one query per eligibility criterion, restricted to the report.
3. **Extraction and appraisal** — one query per data item and per bias domain.
4. **Introduction** — the rationale is written from abstracts retrieved across the whole corpus,
   including excluded records such as earlier reviews, and cites them.
5. **Synthesis and critique** — the writer and the critic receive the same retrieved passages.

Because compression keeps sentences verbatim, a quotation given by the extractor can be checked
against the source by string matching — the basis of the quotation-verification metric.

## 4. PRISMA 2020 alignment

- The manuscript has a fixed structure whose headings map onto the 27 PRISMA items (42 sub-items);
  `tools/prisma.py` holds the mapping and a validator that reports which items are covered.
- The flow diagram is computed from the artifacts and its arithmetic is checked
  (identified − duplicates − automation = screened, and so on down to included studies).
- Records dropped by the relevance cap are reported under "records marked as ineligible by
  automation tools", the PRISMA 2020 category for this.
- Reports without open full text are either assessed on the abstract and flagged throughout, or
  counted as "not retrieved", depending on an option.
- Limitations of the review process are generated from what actually happened in the run (failed
  databases, cap, abstract-only assessments, quotation verification rate, absence of human
  verification).

## 5. Transparency and reproducibility

- `audit.jsonl`: every routing decision, tool call, search, screening decision, extraction, critic
  verdict and human decision, with timestamps.
- `llm_trace.jsonl`: every prompt and response.
- Versioned artifacts: the protocol, strategy, flow, manuscript metadata and QA report keep every
  version.
- Each screening decision stores both reviewers' votes, criteria ids and rationales, how it was
  resolved, and which passages were shown.
- Each extracted value stores its supporting quotation and whether the quotation was found.
- `manifest.json` records the options, the model used for every task and package versions.
- Searches are cached, so a run can be replayed on the same snapshot of results.

## 6. Demonstration

Question: *How accurate are large language models at title and abstract screening for systematic
reviews, compared with human reviewers?* — autonomous mode, Groq free tier, 40 records per
database, 24 records screened, one revision round allowed. All artifacts are in
`examples/demo_run/`.

| Stage | Result | Time |
|---|---|---|
| Protocol | PICO, 5 inclusion and 5 exclusion criteria, 7 data items, 3 databases | cached |
| Search strategy | 5 queries tested live; PubMed 195 hits, Europe PMC 312, Semantic Scholar 221 | 1.1 min |
| Retrieval | 120 records, 8 duplicates, 112 unique, 24 kept by relevance ranking | 0.2 min |
| Title/abstract screening | 20 retained, 4 excluded; kappa 0.83; 1 adjudication | 3.0 min |
| Full-text screening | 10 full texts retrieved, 10 abstract-only; 13 included, 7 excluded; kappa 0.66; 3 adjudications | 6.1 min |
| Extraction and appraisal | 13 studies; 98/109 quotations verified; 12 "some concerns", 1 "unclear" | 15.2 min |
| Synthesis and writing | 4 themes; 8,700 words; 17 references; 42/42 PRISMA items | 6.1 min |
| Critic | 8 issues raised | 3.1 min |

Model calls: 148 (44 answered from the cache). Tokens sent: gpt-oss-120b 61 k, gpt-oss-20b 123 k,
qwen3.8-27b 64 k. Nearly all of the 34.9 minutes is waiting for the per-minute rate limit: the
models answered in 103 seconds in total.

**What the critic found.** Three statements not supported by the evidence (for example, the draft
said specificity was "maintained" where the study reports a drop from 0.99 to 0.98), two
overstatements in the abstract, two narratives with too few citations, and one excluded record
that an independent auditor would include. These are real defects of the first draft and show the
critic doing its job.

**What did not happen.** The revision round. The writing model's daily quota was exhausted when
the critic returned its issues; the pipeline kept the reviewed draft, logged `revision_skipped`,
and wrote the fact into the manuscript's Methods and Limitations. `sysrev revise <run_id>` applies
the revision when quota is available. The critic → writer loop itself is exercised by the workflow
tests and worked in the earlier trial run.

**Deviations from the default configuration**, both forced by the quota: extraction ran on
gpt-oss-20b instead of gpt-oss-120b, and only 24 records were screened.

## 7. Evaluation

### 7.1 Measures on the demonstration run

`sysrev evaluate <run_id>` computes these from the artifacts (`examples/demo_run/evaluation.md`).

| Dimension | Measure | Value |
|---|---|---|
| Completeness | PRISMA 2020 items reported | 42/42 |
| | PRISMA flow arithmetic consistent | yes |
| | Included studies with extraction and appraisal | 13/13 |
| | Data items reported by the studies | 61/89 |
| | Studies read from full text | 8/13 |
| Accuracy | Extraction quotations found in the source | 98/109 (90%) |
| | Citations to non-existent records | 0 |
| | Included studies flagged by the eligibility audit | 0/13 |
| | Unsupported statements / overstatements found by the critic | 3 / 2 (first draft, uncorrected) |
| Consistency | Title/abstract: kappa, raw agreement, conflicts | 0.83, 96%, 1/24 |
| | Full text: kappa, raw agreement, conflicts | 0.66, 85%, 3/20 |
| | Independent re-screening of excluded records | agreed on 3 of 4 |
| Time | Machine time | 0.58 h |
| | Estimated manual effort, same workload | 67.7 person-hours |
| | Per-item tasks only (screening, extraction, appraisal) | 0.41 h vs 22.7 person-hours |

How to read these:

- **Quotation verification** measures grounding, not correctness: a verified quotation proves the
  sentence exists in the source, not that the value was read correctly from it. The 11 unverified
  quotations are flagged in `evidence_table.csv` for a human to check.
- **Kappa** measures agreement between two models, not agreement with the truth. Two models can
  agree and both be wrong, which is what the benchmark below shows.
- **Time**: the manual figure applies the assumptions in `config/manual_effort.yaml` (for example
  45 minutes to extract one study, two reviewers per screening task); it is an estimate. Machine
  time excludes human verification. For context only: reviews registered in PROSPERO took 67.3
  weeks on average to complete and publish (Borah et al., BMJ Open 2017;7:e012545).

### 7.2 Screening accuracy against human decisions

Dataset: Appenzeller-Herzog 2020, a published review of therapies for Wilson disease, from the
ASReview/SYNERGY benchmark collection: 2,358 records with an abstract, of which the human
reviewers kept 161 after title/abstract screening and finally included 29. The planner received
only the review's title and abstract and wrote the protocol; a stratified random sample of 60
records (21 human-kept, 39 human-excluded) was screened by the same agents as in a real review.

| Screener (prompt v1) | Sensitivity | Specificity | F1 | Kappa vs humans |
|---|---|---|---|---|
| Pipeline (A + B + adjudicator) | 0.14 | 1.00 | 0.25 | 0.18 |
| Reviewer A alone (gpt-oss-20b) | 0.19 | 1.00 | 0.32 | 0.23 |
| Reviewer B alone (qwen3.8-27b) | 0.19 | 1.00 | 0.32 | 0.23 |

Kappa between the two AI reviewers: 0.73. Finally-included studies present in the sample: 3; kept
by the pipeline: 3. Time: 7.2 minutes for 60 records.

**Interpretation.** Specificity was perfect and the three studies that mattered in the end were
kept, but against the humans' title/abstract decisions the pipeline missed 18 of 21 records. In 16
of these 18 disagreements the reviewers gave the same reason: the protocol requires a comparator
group, the abstract of a cohort description or case series does not mention one, so they excluded
it. (The other two were a genetics study and an article judged to be a narrative review.) Human
screeners do not exclude on missing information at this stage; they carry the record to full text.
The first prompt said so in one sentence and the models did not follow it.

**Consequence.** The title/abstract prompt was rewritten (v2): exclusion requires positive evidence
of ineligibility, and "not mentioned" is explicitly named as a reason for full-text review, not for
exclusion. The adjudicator's rule was aligned.

**Open item.** v2 has not been measured: the daily quota was used up by the demonstration. Because
the sample above was used to diagnose and fix the prompt, it cannot serve to validate the fix; the
validation must use another sample (`--seed 7`). Until then the only evidence on v2 is indirect:
in the demonstration it kept 20 of 24 records for full-text review, where the exclusions were then
made with reasons.

A sample of 60 records from one review is small; the confidence interval around a sensitivity of
3/21 is wide, and one topic does not generalise. The benchmark command accepts any of the listed
datasets and any sample size.

### 7.3 Software tests

32 automated tests run without network or API key: 29 on the deterministic components and 3 on
the real LangGraph workflow with fake agents (routing, three human checkpoints, protocol-revision
loop, critic loop, resume in a fresh process, reopening a finished run for revision).

## 8. Limitations and future work

- **Scale under the free tier.** 200,000 tokens per model per day limits a review to a few dozen
  screened records. The code has no such limit; a paid tier or local models remove it.
- **Screening sensitivity** must be validated per topic; the benchmark command exists for that.
- **Single extraction.** Extraction and appraisal are done once; dual extraction with reconciliation
  would mirror the screening design.
- **Sources.** No subscription databases, no grey literature, no reference-list chasing; open-access
  full texts only.
- **Meta-analysis** is limited to exploratory pooling of estimates that a model judged comparable.
- **Risk of bias and certainty** are automated and indicative.

## 9. Individual contributions

| Team member | Contribution |
|---|---|
| _to be completed_ | _to be completed_ |
