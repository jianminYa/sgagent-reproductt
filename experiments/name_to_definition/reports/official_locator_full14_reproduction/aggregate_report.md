# Official SGAgent Locator reproduction

This report covers the official Locator workflow only; no name-to-definition arm was run.

- Instances: 45 seeded Lite instances; completed Locator outputs: 44 (0.9777777777777777).
- Termination: `{'completed': 44, 'api_error': 1}`.
- Official repository evaluator: File=0.9111111111111111, Class=0.9111111111111111, Function=0.4222222222222222, Line=0.28888888888888886, IoU=0.16054147491753065.
- Paper set-Jaccard adapter: File=0.8777777777777778, Function=0.5439153439153439.
- Total-token mean/median: 78093.42222222222 / 66830.0; incomplete trajectories: 0.
- LLM-call mean: 11.911111111111111; tool-call mean: 8.688888888888888; latency mean ms: 189687.61675555556.
- Tool usage: {'analyze_file_structure': 52, 'execute_shell_command_with_validation': 1, 'explore_directory': 116, 'extract_complete_method': 53, 'find_class_constructor': 1, 'find_files_containing': 18, 'find_methods_by_name': 14, 'find_variable_usage': 1, 'get_code_relationships': 1, 'list_class_attributes': 1, 'read_file_lines': 87, 'search_code_with_context': 41, 'show_file_imports': 5}.
- Requested models: {'claude-sonnet-5': 45}; returned models: {'claude-sonnet-5': 45}; request IDs recorded/unique/missing: 536/536/0; stop reasons: {'end_turn': 536}.
- Cost: not reported because qtapi pricing was not supplied.

The official repository metrics are containment booleans, while the paper defines FileAcc/FuncAcc as per-instance Jaccard set similarity; both are retained explicitly.
Predicted ranges were converted to synthetic diff hunks only for calling the upstream evaluator offline; the patch was not provided to the agent.

See `instance_results.jsonl` for every instance, including missing/failure records, and `reproduction_gap_report.md` for implementation/data/evaluation differences.
