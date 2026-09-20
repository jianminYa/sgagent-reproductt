# Official SGAgent Locator reproduction

This report covers the official Locator workflow only; no name-to-definition arm was run.

- Instances: 10 seeded Lite instances; completed Locator outputs: 10 (1.0).
- Termination: `{'completed': 10}`.
- Official repository evaluator: File=1.0, Class=0.9, Function=0.4, Line=0.6, IoU=0.25330326209737974.
- Paper set-Jaccard adapter: File=0.925, Function=0.6333333333333333.
- Completed-only conditional metrics: {'n': 10, 'completed': 10, 'official_repository_metrics': {'file_accuracy': 1.0, 'class_accuracy': 0.9, 'function_accuracy': 0.4, 'line_accuracy': 0.6, 'line_iou': 0.25330326209737974}, 'paper_set_jaccard_metrics': {'file_accuracy': 0.925, 'function_accuracy': 0.6333333333333333}}.
- Provider failure: {'count': 0, 'rate': 0.0, 'definition': 'trajectory termination_reason == api_error; HTTP attempts are separately counted'}; HTTP attempts mean/p95/max: 8.3 / 15.549999999999999 / 16.0.
- Bootstrap 95% CI (percentile, 10,000 resamples): official={'file_accuracy': {'n': 10, 'resamples': 10000, 'lower_2_5': 1.0, 'upper_97_5': 1.0}, 'class_accuracy': {'n': 10, 'resamples': 10000, 'lower_2_5': 0.7, 'upper_97_5': 1.0}, 'function_accuracy': {'n': 10, 'resamples': 10000, 'lower_2_5': 0.1, 'upper_97_5': 0.7}, 'line_accuracy': {'n': 10, 'resamples': 10000, 'lower_2_5': 0.3, 'upper_97_5': 0.9}, 'line_iou': {'n': 10, 'resamples': 10000, 'lower_2_5': 0.16545112403935933, 'upper_97_5': 0.34363997113997113}}; paper-Jaccard={'file_accuracy': {'n': 10, 'resamples': 10000, 'lower_2_5': 0.775, 'upper_97_5': 1.0}, 'function_accuracy': {'n': 10, 'resamples': 10000, 'lower_2_5': 0.4166666666666667, 'upper_97_5': 0.8333333333333334}}.
- Total-token mean/median/p95/max: 89318.0 / 61977.5 / 236109.3499999998 / 320510.0; incomplete trajectories: 0.
- Token extremes: highest=[{'instance_id': 'astropy__astropy-7746', 'total_tokens': 320510}, {'instance_id': 'django__django-13768', 'total_tokens': 132953}, {'instance_id': 'django__django-10914', 'total_tokens': 122676}, {'instance_id': 'django__django-12184', 'total_tokens': 84486}, {'instance_id': 'django__django-11630', 'total_tokens': 65164}]; lowest=[{'instance_id': 'sympy__sympy-13647', 'total_tokens': 20131}, {'instance_id': 'django__django-14534', 'total_tokens': 25545}, {'instance_id': 'django__django-11001', 'total_tokens': 30235}, {'instance_id': 'django__django-15814', 'total_tokens': 32689}, {'instance_id': 'django__django-14667', 'total_tokens': 58791}].
- LLM-call mean: 8.2; tool-call mean: 6.2; latency mean ms: 223854.0103.
- Tool-output guard: original/returned chars mean 66353.9 / 66353.9; truncated calls mean 0.0; trajectories with truncation 0.
- Experiment-layer 32,000-character guard enabled values: {'False': 10}; all disabled: True.
- Tool usage: {'analyze_file_structure': 4, 'execute_shell_command_with_validation': 1, 'explore_directory': 1, 'extract_complete_method': 6, 'find_all_variables_named': 1, 'find_files_containing': 8, 'find_methods_by_name': 10, 'find_variable_usage': 3, 'read_file_lines': 24, 'search_code_with_context': 3, 'show_file_imports': 1}.
- Requested models: {'ep-64pmfvfo': 10}; returned models: {'ep-64pmfvfo': 10}; request IDs recorded/unique/missing: 82/82/0; stop reasons: {'stop': 82}.
- Trace validation: {'checked': 10, 'valid': 10, 'invalid': 0, 'note': 'Inherited Phase2 successful trajectories may be legacy traces; no successful sample was rerun for migration.', 'invalid_examples': []}.
- Cost: not reported because qtapi pricing was not supplied.

The official repository metrics are containment booleans, while the paper defines FileAcc/FuncAcc as per-instance Jaccard set similarity; both are retained explicitly.
Predicted ranges were converted to synthetic diff hunks only for calling the upstream evaluator offline; the patch was not provided to the agent.

See `instance_results.jsonl` for every instance, including missing/failure records, and `reproduction_gap_report.md` for implementation/data/evaluation differences.
