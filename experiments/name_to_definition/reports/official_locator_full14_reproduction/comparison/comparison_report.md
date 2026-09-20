# Five-tool versus full 14-tool SGAgent Locator

The preserved five-tool report is compared with the independent full14 run on the same seeded 45-instance manifest.

## Completion

| Run | Completed | Rate | Termination |
|---|---:|---:|---|
| five_tool | 45/45 | 1.000000 | `{'completed': 45}` |
| full14 | 44/45 | 0.977778 | `{'completed': 44, 'api_error': 1}` |

## Metrics (full14 minus five-tool)

| Group / metric | Five-tool | Full14 | Delta |
|---|---:|---:|---:|
| official_repository_metrics / class_accuracy | 0.933333 | 0.911111 | -0.022222 |
| official_repository_metrics / file_accuracy | 0.933333 | 0.911111 | -0.022222 |
| official_repository_metrics / function_accuracy | 0.422222 | 0.422222 | 0.000000 |
| official_repository_metrics / line_accuracy | 0.266667 | 0.288889 | 0.022222 |
| official_repository_metrics / line_iou | 0.164910 | 0.160541 | -0.004369 |
| paper_set_jaccard_metrics / file_accuracy | 0.922222 | 0.877778 | -0.044444 |
| paper_set_jaccard_metrics / function_accuracy | 0.551323 | 0.543915 | -0.007407 |

## Resource statistics (mean and median)

| Group / metric | Five-tool mean | Full14 mean | Delta | Five-tool median | Full14 median |
|---|---:|---:|---:|---:|---:|
| tokens / input | 47222.266667 | 74066.088889 | 26843.822222 | 37054.000000 | 60683.000000 |
| tokens / output | 4866.511111 | 4027.333333 | -839.177778 | 3958.000000 | 3612.000000 |
| tokens / total | 52088.777778 | 78093.422222 | 26004.644444 | 41616.000000 | 66830.000000 |
| calls / failed_tools | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| calls / locator_llm | 12.155556 | 11.066667 | -1.088889 | 11.000000 | 11.000000 |
| calls / summarizer_llm | 1.155556 | 0.844444 | -0.311111 | 1.000000 | 1.000000 |
| calls / tools | 9.866667 | 8.688889 | -1.177778 | 8.000000 | 8.000000 |
| calls / total_llm | 13.311111 | 11.911111 | -1.400000 | 12.000000 | 12.000000 |
| latency_ms / latency_ms | 191844.216378 | 189687.616756 | -2156.599622 | 161768.131000 | 180249.690000 |

## Tool distribution

| Tool | Five-tool | Full14 | Delta |
|---|---:|---:|---:|
| `analyze_file_structure` | 0 | 52 | 52 |
| `execute_shell_command_with_validation` | 5 | 1 | -4 |
| `explore_directory` | 124 | 116 | -8 |
| `extract_complete_method` | 0 | 53 | 53 |
| `find_class_constructor` | 0 | 1 | 1 |
| `find_files_containing` | 0 | 18 | 18 |
| `find_methods_by_name` | 0 | 14 | 14 |
| `find_variable_usage` | 0 | 1 | 1 |
| `get_code_relationships` | 0 | 1 | 1 |
| `list_class_attributes` | 0 | 1 | 1 |
| `read_file_lines` | 177 | 87 | -90 |
| `search_code_with_context` | 135 | 41 | -94 |
| `show_file_imports` | 3 | 5 | 2 |

## Interpretation

- Both reports use the same seeded 45-instance manifest and the same offline evaluator adapter.
- The full14 run uses the latest successful attempt when a transient API failure was retried; failed attempts remain in the run directory.
- Official repository metrics are containment booleans; paper metrics are set Jaccard values.
- The full14 run is Locator-only and is not an N2D ablation.
