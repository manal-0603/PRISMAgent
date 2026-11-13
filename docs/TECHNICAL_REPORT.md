# PRISMAgent — technical report

An agentic AI pipeline for rigorous, transparent and reproducible systematic reviews.

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
| Screening | protocol, records | `screening_*.jsonl`, `agreement_*.json` | Two reviewers on different models, never shown each other's votes; adjudicator sees both rationales. Title/abstract: only positive evidence of ineligibility excludes, and criteria the planner marks "full text only" cannot justify an exclusion |
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

The checkpoints can be answered in the terminal or in the web interface. The interface is a Next.js
application (`web/`) over a small FastAPI layer (`src/sysrev/api.py`) that reads the run folder,
runs the graph in a background thread and resumes it with the reviewer's decision
(`Command(resume=...)`). The layer listens on the local machine only, serves a fixed list of files
per run, and refuses to start a review that another process is already running. Its tests drive a
whole review through the three checkpoints with fake agents (`tests/test_api.py`).

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
reviews, compared with human reviewers?* — autonomous mode, Groq free tier, default options (up to
60 records per database, 50 records screened, two revision rounds). All artifacts are in
`examples/demo_run/`.

| Stage | Result | Time |
|---|---|---|
| Protocol | PICO, 6 inclusion and 6 exclusion criteria (3 marked "full text only"), 8 data items, 4 databases | 0.1 min |
| Search strategy | 7 queries tested live; PubMed 78 hits, Europe PMC 90, arXiv 393, Semantic Scholar 123 | 3.0 min |
| Retrieval | 239 records, 75 duplicates, 164 unique, 50 kept by relevance ranking | 0.3 min |
| Title/abstract screening | 33 retained, 17 excluded; kappa 0.56; 10 adjudications; 3 exclusions blocked by the guard | 8.3 min |
| Full-text screening | 23 full texts retrieved, 10 abstract-only; 21 included, 12 excluded; kappa 0.64; 6 adjudications | 13.3 min |
| Extraction and appraisal | 21 studies; 133/186 quotations verified; 20 "some concerns", 1 "unclear" | 47.7 min |
| Synthesis and writing | 4 themes; 9,700 words; 22 references; 42/42 PRISMA items | 3.4 h |
| Critic, round 1 | 11 issues raised | 1.4 h |
| Revision 1 and critic, round 2 | flagged sections rewritten; 7 issues raised | 2.5 h |
| Revision 2 and critic, round 3 | flagged sections rewritten; 10 issues raised | 1.9 h |

In total 206 model calls (18 answered from the cache) in 10.5 hours; tokens used: gpt-oss-120b
225 k, gpt-oss-20b 143 k, qwen3.8-27b 142 k. The models answered in 4 minutes in total. The rest is
waiting: 9.2 hours for the daily quota of the primary model, which ran out 47 minutes into the run,
during extraction. The run was started with `LLM_MAX_WAIT_SECONDS=3600`, so it waited for the quota
to refill instead of stopping, and advanced one call at a time from there.

**What the critic found (round 1).** Two statements not supported by the evidence (one gives a
record count of 16,670 where the study reports 16,669), two overstatements (the abstract and the
discussion said the models "can reliably identify relevant records"), two narratives with too few
citations, three themes that never cite some of their studies, the low quotation rate, and one
excluded record that an independent auditor would include.

**Two revisions, no convergence.** After the first revision the critic raised 7 issues: the
flagged text had been corrected, but two new unsupported statements and two new overstatements had
appeared. After the second it raised 10: again two unsupported statements and two overstatements,
and the record count of round 1 was still there. The revision budget was then used up. Seven major
issues remain open, five of them for the writer; `qa_report.md` lists them under the verdict "not
resolved" and the manuscript's Methods state it. The lesson is that the critic → writer loop
detects errors reliably but rewriting whole sections produces new ones as fast as it removes the
old: the last word has to be a human's, and a writer that edits only the flagged sentences is the
change to try next.

**The exclusion guard fired three times.** Reviewer A wanted to exclude three records on a
criterion marked "full text only" (no human comparator). The guard turned these votes into
"unsure"; one of the three records is among the 21 included studies.

**Quotation verification: 72%.** 46 of the 53 unverified quotations are fragments from different
places that the extractor joined with "…". The verifier looks for one continuous passage and
rejects them. They are flagged in `evidence_table.csv`. Checking each fragment separately would
separate stitched quotations from invented ones.

**Six reports excluded for lack of a full text.** The planner wrote "full text is available for
data extraction" as an inclusion criterion, and six reports without an open-access copy were
excluded on it. A human team would obtain the papers; this is an availability bias of the run.

## 7. Evaluation

### 7.1 Measures on the demonstration run

`sysrev evaluate <run_id>` computes these from the artifacts (`examples/demo_run/evaluation.md`).

| Dimension | Measure | Value |
|---|---|---|
| Completeness | PRISMA 2020 items reported | 42/42 |
| | PRISMA flow arithmetic consistent | yes |
| | Included studies with extraction and appraisal | 21/21 |
| | Data items reported by the studies | 109/168 |
| | Studies read from full text | 21/21 |
| Accuracy | Extraction quotations found in the source | 133/186 (72%) |
| | Citations to non-existent records | 0 |
| | Included studies flagged by the eligibility audit | 0/21 |
| | Unsupported statements / overstatements found by the critic | 2 / 2 in the first draft; 2 / 2 in the final draft, after two revisions |
| Consistency | Title/abstract: kappa, raw agreement, conflicts | 0.56, 80%, 10/50 |
| | Full text: kappa, raw agreement, conflicts | 0.64, 82%, 6/33 |
| | Independent re-screening of excluded records | agreed on 9 of 10 |
| Time | Machine time | 10.5 h, of which 9.2 h waiting for the daily quota |
| | Estimated manual effort, same workload | 82.2 person-hours |
| | Per-item tasks only (screening, extraction, appraisal) | 1.15 h vs 37.2 person-hours |

How to read these:

- **Quotation verification** measures grounding, not correctness: a verified quotation proves the
  sentence exists in the source, not that the value was read correctly from it. The 53 unverified
  quotations (46 of them stitched from several passages, section 6) are flagged in `evidence_table.csv` for a human to check.
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

**Validation on an independent sample.** Because the first sample had been used to diagnose and fix
the prompt, v2 was tested on a second stratified sample of the same dataset (seed 7, 60 records,
21 human-kept).

| Screener (prompt v2) | Sensitivity | Specificity | F1 | Kappa vs humans |
|---|---|---|---|---|
| Pipeline (A + B + adjudicator) | 0.33 | 1.00 | 0.50 | 0.39 |
| Reviewer A alone (gpt-oss-20b) | 0.24 | 1.00 | 0.38 | 0.29 |
| Reviewer B alone (qwen3.8-27b) | 0.29 | 0.97 | 0.43 | 0.31 |

Kappa between the two AI reviewers: 0.45, with 6 conflicts adjudicated. Finally-included studies
present in the sample: 3; kept by the pipeline: 1.

**Interpretation.** The revision did not solve the problem.

- Sensitivity went from 3/21 to 7/21. The samples differ, and a difference of this size between
  two samples of 21 is compatible with chance (Fisher exact test, p = 0.28).
- Two of the three studies that the published review finally included were excluded. Both were
  retrospective cohorts whose abstracts do not describe a comparator group — exactly the case the
  new rule was written for. Twelve of the 14 disagreements have this cause.
- The models read the instruction and still apply the eligibility criterion literally. A stronger
  wording is unlikely to change this; the constraint should move from the prompt to the code.
- The dual design does add something: the pipeline is more sensitive than either reviewer alone,
  because disagreements go to an adjudicator that includes more readily.

**Third version: criteria marked "full text only".** The constraint was moved from the wording to
the structure of the protocol. `Criterion` gained a `full_text_only` flag that the planner sets for
rules an abstract usually cannot settle; on this topic it marked four criteria (comparator group,
controlled design, outcomes reported, quantitative data). At title/abstract stage the reviewers
and the adjudicator see the mark next to each criterion, and `guard_exclusion` in
`agents/screening.py` converts to "unsure" any exclusion that cites only marked criteria. Tested
on a third unseen sample (seed 21):

| Screener (v3) | Sensitivity | Specificity | F1 | Kappa vs humans |
|---|---|---|---|---|
| Pipeline (A + B + adjudicator) | 0.76 | 0.87 | 0.76 | 0.63 |
| Reviewer A alone (gpt-oss-20b) | 0.67 | 0.85 | 0.68 | 0.52 |
| Reviewer B alone (qwen3.8-27b) | 0.52 | 1.00 | 0.69 | 0.59 |

Kappa between the two AI reviewers: 0.45, with 13 conflicts adjudicated. The one finally-included
study of the sample was kept. Time: 10.3 minutes.

**Interpretation.**

- Sensitivity 16/21 (95% Wilson interval 0.55 to 0.89) against 7/21 for v2 and 3/21 for v1. The
  samples differ, but the difference from v2 is larger than sampling noise explains (Fisher exact
  test, p = 0.012).
- The price is specificity: 34/39 against 39/39. The five false positives are single case reports
  that the adjudicator kept because nothing in the abstract positively violates a criterion — the
  intended behaviour of a sensitive first-pass screen. At the dataset's real prevalence a human
  would still be spared 83% of the records.
- **The code guard never fired.** No exclusion cited only marked criteria. The gain came from the
  reviewers reading the marks: "unsure" votes went from rare to 19 (reviewer A) and 10 (reviewer B)
  out of 60. This is worth stating because the design intent was a guarantee enforced in code, and
  what was measured is a prompt effect.
- The guard can be sidestepped. Four of the five remaining misses are retrospective cohorts that
  both reviewers excluded by citing the marked design criterion together with an unmarked one that
  does not fit (reviewer B: "not primary research"; reviewer A: "other therapies"). An exclusion
  citing any unmarked criterion stands, whatever its merit.
- The dual design keeps paying: the pipeline is more sensitive than either reviewer alone.

**What follows from it.**

1. Screening is much better than it was but 0.76 is still short of what a review needs; a human
   must check the exclusions at checkpoint 2.
2. Next step: require, for every exclusion, a verbatim sentence of the abstract that proves the
   violation, and check it in code — the mechanism that already grounds extraction.
3. The evidence is narrow: one review topic, three samples of 60 records. The benchmark command
   accepts any of the listed datasets and any sample size.
4. Method note: every change was tested on a sample not used to design it. The three samples are
   therefore not paired, and their comparison rests on the tests above.

### 7.3 Software tests

38 automated tests run without network or API key: 33 on the deterministic components, 3 on the
real LangGraph workflow with fake agents (routing, three human checkpoints, protocol-revision
loop, critic loop, resume in a fresh process, reopening a finished run for revision) and 2 on the
HTTP API of the web interface, which drive a whole review through the checkpoints. A GitHub
Actions workflow runs them on every push, with the Python lint (ruff) and the type-check and
production build of the web interface.

## 8. Limitations and future work

- **Scale under the free tier.** 200,000 tokens per model per day limits a review to a few dozen
  screened records, and a review with the default options does not fit in one day of the primary
  model's quota (10.5 hours for the demonstration, section 6). The code has no such limit; a paid
  tier or local models remove it.
- **Revision loop.** Two critic → writer rounds left as many issues as the first draft had. Editing
  only the flagged sentences, instead of rewriting the section, is the next thing to try.
- **Quotation check.** Quotations assembled from several passages are counted as unverified; they
  should be checked fragment by fragment.
- **Screening sensitivity** reached 0.76 on the benchmark topic after three iterations (section 7.2).
  Exclusions still need a human check; quoted evidence for every exclusion is the next step.
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
