# Official SGAgent Locator reproduction

This report covers the official Locator workflow only; no name-to-definition arm was run.

- Instances: 8 seeded Lite instances; completed Locator outputs: 8 (1.0).
- Termination: `{'completed': 8}`.
- Official repository evaluator: File=1.0, Class=1.0, Function=0.25, Line=0.5, IoU=0.13099053724053725.
- Paper set-Jaccard adapter: File=1.0, Function=0.5.
- Total-token mean/median: 80081.75 / 58242.0; incomplete trajectories: 0.
- LLM-call mean: 10.5; tool-call mean: 7.25; latency mean ms: 211548.17925.
- Tool usage: {'analyze_file_structure': 7, 'execute_shell_command_with_validation': 1, 'explore_directory': 19, 'extract_complete_method': 8, 'find_files_containing': 3, 'find_methods_by_name': 4, 'read_file_lines': 13, 'search_code_with_context': 2, 'show_file_imports': 1}.
- Requested models: {'claude-sonnet-5': 8}; returned models: {'claude-sonnet-5': 8}; request IDs recorded/unique/missing: 84/84/0; stop reasons: {'end_turn': 84}.
- Cost: not reported because qtapi pricing was not supplied.

The official repository metrics are containment booleans, while the paper defines FileAcc/FuncAcc as per-instance Jaccard set similarity; both are retained explicitly.
Predicted ranges were converted to synthetic diff hunks only for calling the upstream evaluator offline; the patch was not provided to the agent.

See `instance_results.jsonl` for every instance, including missing/failure records, and `reproduction_gap_report.md` for implementation/data/evaluation differences.
