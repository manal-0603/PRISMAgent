# Evaluation of run `20261111-233350-how-accurate-are-large-language-models-a`

Question: How accurate are large language models at title and abstract screening for systematic reviews, compared with human reviewers?

## Completeness
- **prisma items reported**: 42/42
- **prisma flow arithmetic consistent**: True
- **included studies with extraction**: 21/21
- **included studies with risk of bias**: 21/21
- **data items reported by studies**: 109/168
- **studies read from full text**: 21/21

## Accuracy and grounding
- **extraction quotes verified in source**: 133/186
- **extraction quote verification rate**: 0.7151
- **citations to unknown records final**: 0
- **unsupported statements found by critic first draft**: 2
- **unsupported statements found by critic final draft**: 2
- **critic rounds**: 3
- **eligibility audit flagged included studies**: 0

## Inter-agent consistency
- **title abstract cohen kappa**: 0.5606
- **title abstract interpretation**: moderate
- **title abstract raw agreement**: 0.8
- **title abstract conflicts**: 10/50
- **full text cohen kappa**: 0.64
- **full text interpretation**: substantial
- **full text raw agreement**: 0.8182
- **full text conflicts**: 6/33
- **exclusion audit agreement**: 0.9
- **exclusion audit sample**: 10

## Time
- **pipeline hours**: 10.51
- **manual person hours estimate**: 82.2
- **reduction all tasks**: 0.8721
- **per item tasks manual person hours**: 37.2
- **per item tasks pipeline hours**: 1.15
- **reduction per item tasks**: 0.969
- **note**: Pipeline time is machine wall-clock time, dominated by API rate limits; it excludes human checkpoint time. Manual figures are estimates from config/manual_effort.yaml, not measurements.

| Stage | Pipeline (min) | Manual estimate (person-hours) |
|---|---|---|
| protocol | 0.1 | 8 |
| search_strategy | 3.0 | 6 |
| retrieval | 0.3 | 1 |
| screen_title_abstract | 8.3 | 1.25 |
| screen_full_text | 13.3 | 13.2 |
| extraction | 47.7 | 22.75 |
| synthesis | 557.9 | 30 |

Manual-effort assumptions (edit `config/manual_effort.yaml`):

- title_abstract_screening_min_per_record: 0.75
- full_text_retrieval_min_per_report: 4
- full_text_screening_min_per_report: 10
- data_extraction_min_per_study: 45
- risk_of_bias_min_per_study: 20
- reviewers_per_screening_task: 2
- protocol_hours: 8
- search_strategy_hours: 6
- deduplication_hours: 1
- synthesis_and_writing_hours: 30

## LLM usage
| model | calls | cached | input_tokens | output_tokens | seconds |
|---|---|---|---|---|---|
| openai/gpt-oss-120b | 82 | 12 | 176673 | 48203 | 145.6 |
| openai/gpt-oss-20b | 67 | 3 | 123149 | 19364 | 56.0 |
| qwen/qwen3.8-27b | 57 | 3 | 132144 | 10253 | 45.3 |
