# Evaluation of run `20261110-234913-how-accurate-are-large-language-models-a`

Question: How accurate are large language models at title and abstract screening for systematic reviews, compared with human reviewers?

## Completeness
- **prisma items reported**: 42/42
- **prisma flow arithmetic consistent**: True
- **included studies with extraction**: 13/13
- **included studies with risk of bias**: 13/13
- **data items reported by studies**: 61/89
- **studies read from full text**: 8/13

## Accuracy and grounding
- **extraction quotes verified in source**: 98/109
- **extraction quote verification rate**: 0.8991
- **citations to unknown records final**: 0
- **unsupported statements found by critic first draft**: 3
- **unsupported statements found by critic final draft**: 3
- **critic rounds**: 2
- **eligibility audit flagged included studies**: 0

## Inter-agent consistency
- **title abstract cohen kappa**: 0.8333
- **title abstract interpretation**: almost perfect
- **title abstract raw agreement**: 0.9583
- **title abstract conflicts**: 1/24
- **full text cohen kappa**: 0.6591
- **full text interpretation**: substantial
- **full text raw agreement**: 0.85
- **full text conflicts**: 3/20
- **exclusion audit agreement**: 0.75
- **exclusion audit sample**: 4

## Time
- **pipeline hours**: 1.17
- **manual person hours estimate**: 67.7
- **reduction all tasks**: 0.9828
- **per item tasks manual person hours**: 22.7
- **per item tasks pipeline hours**: 0.41
- **reduction per item tasks**: 0.9821
- **note**: Pipeline time is machine wall-clock time, dominated by API rate limits; it excludes human checkpoint time. Manual figures are estimates from config/manual_effort.yaml, not measurements.

| Stage | Pipeline (min) | Manual estimate (person-hours) |
|---|---|---|
| protocol | 0.0 | 8 |
| search_strategy | 1.1 | 6 |
| retrieval | 0.2 | 1 |
| screen_title_abstract | 3.0 | 0.6 |
| screen_full_text | 6.1 | 8.0 |
| extraction | 15.2 | 14.08 |
| synthesis | 44.3 | 30 |

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
| openai/gpt-oss-120b | 76 | 50 | 59562 | 8982 | 29.8 |
| openai/gpt-oss-20b | 59 | 7 | 98736 | 24109 | 55.9 |
| qwen/qwen3.8-27b | 34 | 1 | 72484 | 6265 | 25.9 |
