# Screening benchmark — Appenzeller-Herzog_2020 (screening prompt v1, development sample)

> Archived result of the FIRST version of the title/abstract screening prompt. It showed that the reviewers excluded
> records whose abstract merely did not mention a comparator; the prompt was revised (v2) because of this result.

Review: *Comparative effectiveness of common therapies for Wilson disease: A systematic review and meta-analysis of controlled studies* (https://doi.org/10.1111/liv.14179)

- Records with an abstract in the dataset: 2358; kept by the human reviewers at title/abstract stage: 161 (6.8%)
- Stratified sample screened by the pipeline: 60 records (21 human-kept, 39 human-excluded), seed 13
- Reference standard: `label_abstract_screening`. The agents received only the review's title and abstract.

| Screener | Sensitivity | Specificity | Precision (sample) | F1 | Kappa vs humans | TP | FP | FN | TN |
|---|---|---|---|---|---|---|---|---|---|
| Pipeline (A + B + adjudicator) | 0.1429 | 1.0 | 1.0 | 0.2501 | 0.1781 | 3 | 0 | 18 | 39 |
| Reviewer A alone (openai/gpt-oss-20b) | 0.1905 | 1.0 | 1.0 | 0.32 | 0.2342 | 4 | 0 | 17 | 39 |
| Reviewer B alone (qwen/qwen3.8-27b) | 0.1905 | 1.0 | 1.0 | 0.32 | 0.2342 | 4 | 0 | 17 | 39 |

Adjudicator: openai/gpt-oss-120b. Protocol written by: openai/gpt-oss-120b.

- Agreement between the two AI reviewers: kappa = 0.7321 (substantial); 2 conflicts adjudicated
- Studies finally included in the published review that were in the sample: 3; kept by the pipeline: 3
- Precision re-weighted to the dataset prevalence: 1.0; share of records a human would not need to read: 0.9902
- Time: 7.2 min for 60 records (7.2 s per record, including API rate-limit waits; cached calls are instantaneous)

Precision in the sample is inflated by over-sampling of human-kept records; use the re-weighted value.

## Disagreements with the human reviewers

| rid | human | pipeline | finally_included | title | rationale |
|---|---|---|---|---|---|
| R0008 | keep | exclude | False | Wilson disease: description of 282 patients evaluated over 3 decades | A: Cohort study of 282 WD patients without a comparator group. / B: This is a retrospective cohort description of 282 patients without a comparator group or control arm. |
| R0009 | keep | exclude | False | Neuro-Wilson disease - about seven cases and review of the literature | A: Case series of 7 WD patients, no control or comparator arm. / B: The study reports on seven cases without a defined control group or comparator for the treatments administered. |
| R0015 | keep | exclude | False | Wilson's disease: A Canadian perspective on the presentation and clinical outcomes in an adult ambulatory sett | A: Retrospective chart review without a control or comparator group. / B: This is a retrospective chart review of a single cohort without a control group or comparator, failing the inclusion criterion for a controlled study. |
| R0017 | keep | exclude | False | The first study of Wilson's disease prevalence in a Portuguese population | A: Prevalence study, no intervention or comparator. / B: This is a retrospective prevalence study of a single cohort without a comparator group, failing the requirement for a controlled design. |
| R0018 | keep | exclude | False | Significant heterogeneity in the diagnosis and management of wilson disease (WD): Results from a large spanish | A: Observational descriptive study without a comparator group. / B: This is a descriptive registry study of a single cohort without a control group or comparator, failing the inclusion criterion for a controlled study. |
| R0024 | keep | exclude | False | Clinical assessment of 31 patients with Wilson's disease. Correlations with structural changes on magnetic res | A: No comparator group, only observational data. / B: The study describes clinical and MRI findings in a single cohort of Wilson disease patients without a control group or comparative intervention analysis. |
| R0025 | keep | exclude | False | Wilson's disease: an analysis of 28 Brazilian children | A: No control group, only treated patients reported. / B: The study is a retrospective analysis of 28 patients without a distinct control group or comparator arm. |
| R0029 | keep | exclude | False | Withdrawal of penicillamine from zinc sulphate-penicillamine maintenance therapy in Wilson's disease: promisin | The abstract describes a single cohort of Wilson disease patients who had penicillamine withdrawn and continued zinc alone; there is no separate control or comparator group, only a before‑after observation within the same participants. This violates exclusion criterion E3 (study lacks a comparator g |
| R0031 | keep | exclude | False | Triethylene-tetramine (trien) therapy for Wilson's disease | The abstract describes a small case series of four Wilson disease patients treated with trientine (trien) and references a retrospective survey of other patients, but it does not present a concurrent control group or comparator arm within the study. Therefore it fails the required comparator criteri |
| R0036 | keep | exclude | False | High frequency of the c.3207C>A (p.H1069Q) mutation in ATP7B gene of Lithuanian patients with hepatic presenta | A: Study on ATP7B mutation, no therapeutic intervention. / B: The study investigates genetic mutation prevalence in Wilson disease patients and does not report on the comparative effectiveness of the specified therapies. |
| R0038 | keep | exclude | False | Subclinical neurological involvement does not develop if Wilson's disease is treated early | A: Observational study with no control group, only treatment groups. / B: The study evaluates early-treated patients without a concurrent control group or comparator arm, failing the controlled study design requirement. |
| R0043 | keep | exclude | False | Wilson's disease in southern Brazil: A 40-year follow-up study | A: Retrospective cohort with no comparator group defined. / B: The study is a retrospective cohort of 36 patients without a comparator group, failing the requirement for a control arm. |
| R0047 | keep | exclude | False | Wilson's disease in Thai children between 2000 and 2012 at king chulalongkorn memorial hospital | A: All patients received chelation, no comparator group. / B: The study describes a cohort of 21 children without a comparator group or control arm. |
| R0048 | keep | exclude | False | Maintenance Zinc therapy after initial Penicillamine chelation to treat symptomatic hepatic Wilson's disease i | A: Retrospective before‑after without control group. / B: The study analyzes a single cohort of 31 patients over time without a concurrent control group or comparator therapy. |
| R0053 | keep | exclude | False | Geographic variations in Wilson's disease | A: Review article, not primary research. / B: The text describes geographic variations and general observations, indicating it is a narrative review rather than a primary controlled trial. |
| R0054 | keep | exclude | False | Long-term evaluation of urinary copper excretion and non-caeruloplasmin associated copper in Wilson disease pa | A: Retrospective cohort with no control group. / B: This is a retrospective cohort study monitoring biomarkers in treated patients without a control group or comparator. |
| R0055 | keep | exclude | False | Wilson's disease with hepatic presentation in childhood | A: Study reports treatment with D‑penicillamine and zinc but lacks a comparator group. / B: The study is a retrospective cohort of 34 children treated with D-penicillamine and zinc but lacks a control group or comparator. |
| R0059 | keep | exclude | False | Oromandibular Dystonia in Wilson's Disease | A: Observational study of treatment but no comparator group, so fails inclusion. / B: The study is a single-arm observational cohort of Wilson disease patients without a comparator group. |
