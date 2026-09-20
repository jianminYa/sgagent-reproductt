# Paired Full14 versus no-N2D smoke

Paired sample size: **10**. Deltas are `no_n2d - full14`.

## Completion and trace gate

| Arm | Completed | Rate | Provider failures | Valid traces |
|---|---:|---:|---:|---:|
| full14 | 10/10 | 1.000000 | 0 | 10/10 |
| no_n2d | 10/10 | 1.000000 | 0 | 10/10 |

## Aggregate metrics

| Group / metric | Full14 | no-N2D | Delta |
|---|---:|---:|---:|
| official_repository_metrics / class_accuracy | 0.900000 | 0.900000 | 0.000000 |
| official_repository_metrics / file_accuracy | 1.000000 | 1.000000 | 0.000000 |
| official_repository_metrics / function_accuracy | 0.400000 | 0.400000 | 0.000000 |
| official_repository_metrics / line_accuracy | 0.600000 | 0.600000 | 0.000000 |
| official_repository_metrics / line_iou | 0.253303 | 0.306807 | 0.053503 |
| paper_set_jaccard_metrics / file_accuracy | 0.925000 | 0.925000 | 0.000000 |
| paper_set_jaccard_metrics / function_accuracy | 0.633333 | 0.625000 | -0.008333 |

## Per-instance direction

| Metric | no-N2D better | Full14 better | Tie |
|---|---:|---:|---:|
| file_match | 0 | 0 | 10 |
| class_match | 0 | 0 | 10 |
| function_match | 0 | 0 | 10 |
| line_match | 0 | 0 | 10 |
| line_iou | 3 | 3 | 4 |
| paper_file_jaccard | 0 | 0 | 10 |
| paper_function_jaccard | 1 | 2 | 7 |

## Resource deltas

| Group / metric | Full14 mean | no-N2D mean | Delta | Full14 median | no-N2D median |
|---|---:|---:|---:|---:|---:|
| tokens / input | 87271.000000 | 174960.400000 | 87689.400000 | 59030.500000 | 99033.500000 |
| tokens / output | 2047.000000 | 1914.200000 | -132.800000 | 2358.500000 | 1715.000000 |
| tokens / total | 89318.000000 | 176874.600000 | 87556.600000 | 61977.500000 | 102265.000000 |
| calls / failed_logical_llm | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| calls / failed_tools | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| calls / http_attempts | 8.300000 | 8.000000 | -0.300000 | 6.500000 | 7.500000 |
| calls / locator_llm | 7.800000 | 7.600000 | -0.200000 | 6.500000 | 7.500000 |
| calls / logical_llm | 8.200000 | 7.900000 | -0.300000 | 6.500000 | 7.500000 |
| calls / request_retries | 0.100000 | 0.100000 | 0.000000 | 0.000000 | 0.000000 |
| calls / successful_responses | 8.200000 | 7.900000 | -0.300000 | 6.500000 | 7.500000 |
| calls / summarizer_llm | 0.400000 | 0.300000 | -0.100000 | 0.000000 | 0.000000 |
| calls / tools | 6.200000 | 6.700000 | 0.500000 | 5.000000 | 6.000000 |
| calls / total_llm | 8.200000 | 7.900000 | -0.300000 | 6.500000 | 7.500000 |

## Notes

- Both arms use the same explicit 10-instance set, model, protocol, timeout, worker count, retry policy, and offline evaluator.
- Deltas are no_n2d minus full14; positive values favor no_n2d for metrics and indicate higher resource use for resource fields.
- This is pilot-scale paired evidence and does not establish statistical significance or justify scaling beyond the smoke gate by itself.
