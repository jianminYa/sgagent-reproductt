# Official SGAgent Locator reproduction

This report covers the official Locator workflow only; no name-to-definition arm was run.

- Instances: 45 seeded Lite instances; completed Locator outputs: 44 (0.9777777777777777).
- Termination: `{'completed': 44, 'api_error': 1}`.
- Official repository evaluator: File=0.8666666666666667, Class=0.8444444444444444, Function=0.4, Line=0.3333333333333333, IoU=0.23612117988312167.
- Paper set-Jaccard adapter: File=0.8444444444444444, Function=0.562962962962963.
- Total-token mean/median: 110983.06666666667 / 74751.0; incomplete trajectories: 0.
- LLM-call mean: 10.355555555555556; tool-call mean: 8.666666666666666; latency mean ms: 156891.59666666668.
- Tool-output guard: original/returned chars mean 110093.77777777778 / 41737.4; truncated calls mean 0.8; trajectories with truncation 24.
- Tool usage: {'analyze_file_structure': 28, 'execute_shell_command_with_validation': 39, 'explore_directory': 19, 'extract_complete_method': 64, 'find_all_variables_named': 3, 'find_class_constructor': 10, 'find_files_containing': 49, 'find_methods_by_name': 47, 'find_variable_usage': 12, 'read_file_lines': 107, 'search_code_with_context': 18, 'show_file_imports': 3}.
- Requested models: {'ep-64pmfvfo': 45}; returned models: {'ep-64pmfvfo': 45}; request IDs recorded/unique/missing: 466/466/0; stop reasons: {'stop': 466}.
- Cost: not reported because qtapi pricing was not supplied.

The official repository metrics are containment booleans, while the paper defines FileAcc/FuncAcc as per-instance Jaccard set similarity; both are retained explicitly.
Predicted ranges were converted to synthetic diff hunks only for calling the upstream evaluator offline; the patch was not provided to the agent.

See `instance_results.jsonl` for every instance, including missing/failure records, and `reproduction_gap_report.md` for implementation/data/evaluation differences.
