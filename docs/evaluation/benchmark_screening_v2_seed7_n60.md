# Screening benchmark — Appenzeller-Herzog_2020 (screening prompt v2, validation sample)

> Independent sample (seed 7) drawn to test the revised title/abstract prompt. The sample of the v1 report (seed 13)
> was used to diagnose the problem and could not serve to validate the fix.

Review: *Comparative effectiveness of common therapies for Wilson disease: A systematic review and meta-analysis of controlled studies* (https://doi.org/10.1111/liv.14179)

- Records with an abstract in the dataset: 2358; kept by the human reviewers at title/abstract stage: 161 (6.8%)
- Stratified sample screened by the pipeline: 60 records (21 human-kept, 39 human-excluded), seed 7
- Reference standard: `label_abstract_screening`. The agents received only the review's title and abstract. Screening prompt v2.

| Screener | Sensitivity | Specificity | Precision (sample) | F1 | Kappa vs humans | TP | FP | FN | TN |
|---|---|---|---|---|---|---|---|---|---|
| Pipeline (A + B + adjudicator) | 0.3333 | 1.0 | 1.0 | 0.5 | 0.3939 | 7 | 0 | 14 | 39 |
| Reviewer A alone (openai/gpt-oss-20b) | 0.2381 | 1.0 | 1.0 | 0.3846 | 0.2889 | 5 | 0 | 16 | 39 |
| Reviewer B alone (qwen/qwen3.8-27b) | 0.2857 | 0.9744 | 0.8571 | 0.4285 | 0.3074 | 6 | 1 | 15 | 38 |

Adjudicator: openai/gpt-oss-120b. Protocol written by: openai/gpt-oss-120b.

- Agreement between the two AI reviewers: kappa = 0.4462 (moderate); 6 conflicts adjudicated
- Studies finally included in the published review that were in the sample: 3; kept by the pipeline: 1
- Precision re-weighted to the dataset prevalence: 1.0; share of records a human would not need to read: 0.9772
- Time: 64.0 min for 60 records (64.0 s per record, including API rate-limit waits; cached calls are instantaneous)

Precision in the sample is inflated by over-sampling of human-kept records; use the re-weighted value.

## Disagreements with the human reviewers

| rid | human | pipeline | finally_included | title | rationale |
|---|---|---|---|---|---|
| R0003 | keep | exclude | False | Practical recommendations and new therapies for Wilson's disease | A: The abstract is a review, not an original study. / B: The title and abstract indicate the paper provides practical recommendations and a general overview of therapies, consistent with a review or guideline document. |
| R0005 | keep | exclude | False | A clinical study of Wilson's disease: The experience of a single Egyptian Paediatric Hepatology Unit | A: All patients received treatment; no control group mentioned. / B: The study describes a single cohort of 54 patients treated with penicillamine and zinc without any mention of a control or comparator group. |
| R0009 | keep | exclude | False | Prognostic significance of neurologic examination findings in Wilson disease | The abstract reports a single cohort of Wilson disease patients receiving anticopper therapy (tetrathiomolybdate, trientine, zinc) with no comparator group. Eligibility requires a control group (placebo, no treatment, or another eligible therapy). Since the study lacks a comparator, it violates excl |
| R0014 | keep | exclude | False | Wilson's disease. Different forms of onset. [Spanish] | A: Retrospective study of 7 cases but no comparator group is described in the abstract. / B: Retrospective case series of 7 cases without a comparator group, failing criteria for controlled study design. |
| R0016 | keep | exclude | False | Clinical efficacy and safety of chelation treatment with typical penicillamine in cross combination with DMPS  | A: No control or comparator group is mentioned in the abstract. / B: Evaluates a combination including DMPS (not an eligible agent) and appears to be a single-arm study without a distinct comparator group. |
| R0020 | keep | exclude | False | Early neurological worsening in wilson's disease patients | A: No control or comparator group reported in abstract. / B: The study analyzes a single cohort of 143 patients without a control group or comparator arm. |
| R0021 | keep | exclude | False | Geographic variations in Wilson's disease | A: Review article, not primary research. / B: The text describes geographic variations and cites 77 references, indicating it is a narrative review rather than a primary study. |
| R0024 | keep | exclude | False | Neuro-Wilson disease - about seven cases and review of the literature | A: Case series, no comparator group in abstract. / B: The study is a case series of seven patients with a literature review, lacking a control group or comparative design. |
| R0031 | keep | exclude | True | Clinical presentation, diagnosis and long-term outcome of Wilson's disease: a cohort study | A: Retrospective cohort without a control group, only observational outcomes. / B: The study is a retrospective cohort analysis of 163 patients without a specified comparator group for treatment outcomes. |
| R0035 | keep | exclude | False | Wilson's disease: Cranial MRI observations and clinical correlation | A: MRI study of Wilson disease patients, no treatment comparison. / B: The study correlates MRI findings with clinical features in a single cohort without a control group or comparative treatment analysis. |
| R0043 | keep | exclude | False | Concomitant immune mediated phenomenon in wilson disease: Implication for monitoring of chelator therapy | A: Retrospective cohort with no control group, only treatment arms reported. / B: The study is a retrospective cohort analyzing adverse events in a single group of patients without a comparator group. |
| R0048 | keep | exclude | False | Wilson's disease in Oman: A study of neurological manifestations and diagnostic delay from a University Teachi | A: Observational study without a comparator group. / B: The study is a descriptive case series of neurological manifestations without a control or comparator group. |
| R0051 | keep | exclude | True | Histologic evolution and long-term outcome of Wilson's disease: results of a single-center experience | A: Retrospective study with zinc/penicillamine but no comparator group is described. / B: This is a retrospective single-center analysis of 60 patients without a distinct control group or comparator arm. |
| R0054 | keep | exclude | False | Wilson's disease: Experience with 71 patients followed for two decades in a Tertiary Centre in Saudi Arabia | A: Observational cohort with no comparator group mentioned. / B: This is a retrospective review of 71 patients at a single center without a specified control group or comparator. |
