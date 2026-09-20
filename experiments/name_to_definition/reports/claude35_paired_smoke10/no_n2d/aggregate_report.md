# Official SGAgent Locator reproduction

This report covers the official Locator workflow only; no name-to-definition arm was run.

- Instances: 10 seeded Lite instances; completed Locator outputs: 10 (1.0).
- Termination: `{'completed': 10}`.
- Official repository evaluator: File=1.0, Class=0.9, Function=0.4, Line=0.6, IoU=0.3068066378066378.
- Paper set-Jaccard adapter: File=0.925, Function=0.625.
- Completed-only conditional metrics: {'n': 10, 'completed': 10, 'official_repository_metrics': {'file_accuracy': 1.0, 'class_accuracy': 0.9, 'function_accuracy': 0.4, 'line_accuracy': 0.6, 'line_iou': 0.3068066378066378}, 'paper_set_jaccard_metrics': {'file_accuracy': 0.925, 'function_accuracy': 0.625}}.
- Provider failure: {'count': 0, 'rate': 0.0, 'definition': 'trajectory termination_reason == api_error; HTTP attempts are separately counted'}; HTTP attempts mean/p95/max: 8.0 / 14.099999999999998 / 15.0.
- Bootstrap 95% CI (percentile, 10,000 resamples): official={'file_accuracy': {'n': 10, 'resamples': 10000, 'lower_2_5': 1.0, 'upper_97_5': 1.0}, 'class_accuracy': {'n': 10, 'resamples': 10000, 'lower_2_5': 0.7, 'upper_97_5': 1.0}, 'function_accuracy': {'n': 10, 'resamples': 10000, 'lower_2_5': 0.1, 'upper_97_5': 0.7}, 'line_accuracy': {'n': 10, 'resamples': 10000, 'lower_2_5': 0.3, 'upper_97_5': 0.9}, 'line_iou': {'n': 10, 'resamples': 10000, 'lower_2_5': 0.2072323232323232, 'upper_97_5': 0.40669552669552667}}; paper-Jaccard={'file_accuracy': {'n': 10, 'resamples': 10000, 'lower_2_5': 0.775, 'upper_97_5': 1.0}, 'function_accuracy': {'n': 10, 'resamples': 10000, 'lower_2_5': 0.4083333333333333, 'upper_97_5': 0.8333333333333334}}.
- Total-token mean/median/p95/max: 176874.6 / 102265.0 / 511667.54999999964 / 668691.0; incomplete trajectories: 0.
- Token extremes: highest=[{'instance_id': 'django__django-14667', 'total_tokens': 668691}, {'instance_id': 'astropy__astropy-7746', 'total_tokens': 319750}, {'instance_id': 'django__django-11001', 'total_tokens': 287197}, {'instance_id': 'django__django-13768', 'total_tokens': 135405}, {'instance_id': 'django__django-10914', 'total_tokens': 122564}]; lowest=[{'instance_id': 'django__django-14534', 'total_tokens': 20430}, {'instance_id': 'sympy__sympy-13647', 'total_tokens': 37606}, {'instance_id': 'django__django-15814', 'total_tokens': 42277}, {'instance_id': 'django__django-12184', 'total_tokens': 52860}, {'instance_id': 'django__django-11630', 'total_tokens': 81966}].
- LLM-call mean: 7.9; tool-call mean: 6.7; latency mean ms: 213256.1072.
- Tool-output guard: original/returned chars mean 142177.7 / 142177.7; truncated calls mean 0.0; trajectories with truncation 0.
- Experiment-layer 32,000-character guard enabled values: {'False': 10}; all disabled: True.
- Tool usage: {'analyze_file_structure': 4, 'execute_shell_command_with_validation': 2, 'explore_directory': 2, 'extract_complete_method': 10, 'find_files_containing': 9, 'find_variable_usage': 4, 'read_file_lines': 26, 'search_code_with_context': 9, 'show_file_imports': 1}.
- Requested models: {'ep-64pmfvfo': 10}; returned models: {'ep-64pmfvfo': 10}; request IDs recorded/unique/missing: 79/79/0; stop reasons: {'stop': 79}.
- Trace validation: {'checked': 10, 'valid': 10, 'invalid': 0, 'note': 'Inherited Phase2 successful trajectories may be legacy traces; no successful sample was rerun for migration.', 'invalid_examples': []}.
- Cost: not reported because qtapi pricing was not supplied.

The official repository metrics are containment booleans, while the paper defines FileAcc/FuncAcc as per-instance Jaccard set similarity; both are retained explicitly.
Predicted ranges were converted to synthetic diff hunks only for calling the upstream evaluator offline; the patch was not provided to the agent.

See `instance_results.jsonl` for every instance, including missing/failure records, and `reproduction_gap_report.md` for implementation/data/evaluation differences.
