# Quality-assurance report

**Verdict:** not resolved — 7 critical or major issues still open; no further automatic revision

## Checks

- **round**: 3
- **prisma_flow_consistent**: True
- **prisma_items_reported**: 42
- **prisma_items_total**: 42
- **unknown_citations**: []
- **included_without_extraction**: []
- **uncited_sentence_ratio**: {'High sensitivity screening models': 0.25, 'Ensemble and prompt‑optimization approaches': 0.38, 'Fine‑tuned or specialized LLMs': 0.29, 'Other findings': 0.17}
- **extraction_quotes**: {'quotes_checked': 186, 'quotes_verified': 133, 'verification_rate': 0.7151}
- **unsupported_statements**: 2
- **overstatements**: 2
- **exclusion_audit**: {'sampled': 10, 'judged': 10, 'auditor_would_include': ['R0088'], 'agreement': 0.9}
- **eligibility_audit**: {'checked': 21, 'flagged': []}

## Issues

- **minor** [synthesis:High sensitivity screening models] Studies assigned to this theme are never cited in its narrative: R0014, R0035, R0096. *Suggested fix:* Report what these studies found, or explain why they add nothing.
- **major** [synthesis:Ensemble and prompt‑optimization approaches] 38% of the sentences in this narrative carry no citation. *Suggested fix:* End every sentence reporting a finding with the ids of the studies it comes from.
- **minor** [synthesis:Ensemble and prompt‑optimization approaches] Studies assigned to this theme are never cited in its narrative: R0103, R0145. *Suggested fix:* Report what these studies found, or explain why they add nothing.
- **minor** [synthesis:Fine‑tuned or specialized LLMs] Studies assigned to this theme are never cited in its narrative: R0045, R0058, R0085. *Suggested fix:* Report what these studies found, or explain why they add nothing.
- **major** [extraction] Only 72% of the extraction quotations were found in the source texts. *Suggested fix:* A human should verify the values flagged 'unverified' in evidence_table.csv.
- **major** [synthesis:High sensitivity screening models] Unsupported statement: "Across studies, higher sensitivities are associated with larger LLMs (GPT‑4 variants), refined prompts, and fine‑tuning" — The evidence does not support the claim that larger LLMs are associated with higher sensitivity. Specifically, [R0037] shows that the larger Llama 3 70B model achieved higher sensitivity (77.5%) than the smaller ChatGPT-4o mini (56.2%), but [R0011] shows GPT-4 (large) achieving 90-97% sensitivity, while [R0073] shows ChatGPT 4.0 (large) achieving only 88-89% sensitivity. More critically, [R0096] demonstrates that fine-tuning a *small* 1.2B parameter model (LiquidAI LFM2.5) achieved 91.18% sensitivity, which is higher than the 88-89% reported for the large ChatGPT 4.0 in [R0073] and comparable to GPT-4 in [R0011]. Thus, model size is not consistently associated with higher sensitivity in the provided evidence; fine-tuning a small model can outperform or match large general-purpose models. *Suggested fix:* Revise the statement to reflect that high sensitivity is associated with refined prompts and fine-tuning (as shown in [R0010], [R0079], and [R0096]), but avoid claiming a direct association with larger model size, as small fine-tuned models ([R0096]) also achieved high sensitivity (>90%).
- **major** [synthesis:Ensemble and prompt‑optimization approaches] Unsupported statement: "In Oami et al., modifying the prompt raised integrated sensitivity from 0.75 to 0.91 while specificity remained above 0.98, demonstrating the impact of prompt engineering on a dataset of 16,670 records [R0010]." — The number of records is incorrect. The evidence states the sample size was 16,669 records, not 16,670. *Suggested fix:* Change '16,670 records' to '16,669 records'.
- **major** [abstract] "LLMs demonstrate moderate-to-high sensitivity for title and abstract screening, often matching or exceeding human reviewers" — The thematic synthesis does not support the claim that LLMs 'match or exceed' human reviewers. While one study (Guo et al.) showed higher inter-rater agreement for the LLM than between two humans, other studies (e.g., Nordmann et al., López-Pineda et al.) reported lower sensitivities for LLMs compared to human reference standards or showed performance variability that does not establish superiority. The synthesis describes performance relative to reference standards but does not conclude that LLMs generally match or exceed human performance. *Suggested fix:* Revise the conclusion to state that LLMs demonstrate variable sensitivity, with high-performing models achieving sensitivities comparable to or exceeding human reviewers in specific contexts, while acknowledging that performance varies significantly by model and prompt.
- **major** [discussion] "The findings suggest that LLMs, particularly when fine-tuned or used within ensemble and prompt-optimized workflows, can reliably support title and abstract screening, potentially reducing reviewer workload while maintaining high sensitivity." — The term 'reliably' is too strong given the 'moderate' certainty of the evidence and the noted inconsistencies in reference standards and reporting. The synthesis highlights significant variability in sensitivity (ranging from 56% to 100%) and precision issues, which undermines a blanket claim of reliability without qualification. *Suggested fix:* Soften the language to suggest that LLMs 'can support' or 'have the potential to support' screening, noting that reliability depends on rigorous prompt engineering and ensemble methods, and acknowledging the current limitations in consistency.
- **major** [screening] R0088 was excluded at title/abstract stage but an independent auditor would include it: Experimental study comparing LLMs to human reviewers for title‑abstract screening with reported performance metrics. *Suggested fix:* Human reviewer to re-check this record.
