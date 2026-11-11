# Screening benchmark — Appenzeller-Herzog_2020 (screening v3: full-text-only criteria, third sample)

> Third independent sample (seed 21). The planner now marks the criteria that only a full text can settle; the
> reviewers see the mark and the code refuses exclusions resting solely on those criteria.

Review: *Comparative effectiveness of common therapies for Wilson disease: A systematic review and meta-analysis of controlled studies* (https://doi.org/10.1111/liv.14179)

- Records with an abstract in the dataset: 2358; kept by the human reviewers at title/abstract stage: 161 (6.8%)
- Stratified sample screened by the pipeline: 60 records (21 human-kept, 39 human-excluded), seed 21
- Reference standard: `label_abstract_screening`. The agents received only the review's title and abstract. Screening prompt v3.

| Screener | Sensitivity | Specificity | Precision (sample) | F1 | Kappa vs humans | TP | FP | FN | TN |
|---|---|---|---|---|---|---|---|---|---|
| Pipeline (A + B + adjudicator) | 0.7619 | 0.8718 | 0.7619 | 0.7619 | 0.6337 | 16 | 5 | 5 | 34 |
| Reviewer A alone (openai/gpt-oss-20b) | 0.6667 | 0.8462 | 0.7 | 0.6829 | 0.5185 | 14 | 6 | 7 | 33 |
| Reviewer B alone (qwen/qwen3.8-27b) | 0.5238 | 1.0 | 1.0 | 0.6875 | 0.5885 | 11 | 0 | 10 | 39 |

Adjudicator: openai/gpt-oss-120b. Protocol written by: openai/gpt-oss-120b.

- Agreement between the two AI reviewers: kappa = 0.4507 (moderate); 13 conflicts adjudicated
- Criteria the planner marked as full-text only: E5, I3, I4, I5; exclusion votes converted to 'unsure' by the code guard: 0
- Studies finally included in the published review that were in the sample: 1; kept by the pipeline: 1
- Precision re-weighted to the dataset prevalence: 0.3034; share of records a human would not need to read: 0.8285
- Time: 10.3 min for 60 records (10.3 s per record, including API rate-limit waits; cached calls are instantaneous)

Precision in the sample is inflated by over-sampling of human-kept records; use the re-weighted value.

## Disagreements with the human reviewers

| rid | human | pipeline | finally_included | title | rationale |
|---|---|---|---|---|---|
| R0004 | exclude | include | False | A copper-sulfur complex in the liver of a patient with Wilson's disease | The abstract describes a single-patient case report of d‑penicillamine treatment without mentioning a comparator or outcomes, but the lack of a comparator group and the study design (case report) are criteria that are marked as [full text only]. At the title/abstract stage we cannot exclude based on |
| R0005 | exclude | include | False | Hypersomnolence in Wilson Disease | The abstract describes a single case report without providing information that definitively violates any inclusion or exclusion criteria. Although the study likely lacks a comparator and does not report the required outcomes, these are full‑text‑only criteria (I3, I4, I5) and cannot be used to exclu |
| R0011 | keep | exclude | False | Wilson disease in children; A six-year experience, 2001-2008 | A: Retrospective chart review without a comparator drug group. / B: Retrospective chart review of 11 patients without a comparator group, failing the controlled study design requirement. |
| R0012 | keep | exclude | False | Wilson's disease: Experience with 71 patients followed for two decades in a Tertiary Centre in Saudi Arabia | A: Retrospective cohort without a comparator therapy group. / B: Retrospective cohort of 71 patients without a comparator group, failing the controlled study design requirement. |
| R0016 | exclude | include | False | Wilson's disease: a common liver disorder? | The abstract describes a case series of patients with Wilson disease receiving D-penicillamine, but it does not provide explicit evidence that the study violates any exclusion criteria at the title/abstract stage. The lack of a comparator and the uncontrolled design are marked as full‑text‑only crit |
| R0019 | exclude | include | False | Low-dose zinc administration as an effective Wilson's disease treatment | The abstract describes a single-patient case report without a comparator, indicating that the study design does not meet the required controlled designs. However, the design criterion (I5) is marked as [full text only], so it cannot be used to exclude the record at the title/abstract screening stage |
| R0020 | keep | exclude | False | Practical recommendations and new therapies for Wilson's disease | A: Review article, not a primary research report. / B: The title and abstract indicate a narrative review or practical recommendation paper, not a primary research report. |
| R0024 | keep | exclude | False | Effective shift from traditional chelation therapy to evidence based zinc monotherapy in four patients with Wi | A: Retrospective observational study without a comparator group, thus not meeting comparative design requirement. / B: The study is a retrospective observational case series of four patients without a distinct comparator group, failing the controlled design requirement. |
| R0026 | exclude | include | False | Symptomatic copper deficiency in three Wilson's disease patients treated with zinc sulphate | The abstract reports a case series of Wilson disease patients treated with zinc, but it does not provide enough information to confirm a violation of any exclusion criteria at the title/abstract stage. The lack of a comparator and specific outcomes cannot be used to exclude because those criteria ar |
| R0054 | keep | exclude | False | Wilson's diseases: Single center's 1 year overall experience | A: Single center experience, no treatment comparison. / B: The record describes a single-center experience with 5 patients, constituting a case series rather than an eligible controlled study design. |
