# Official SGAgent Locator reproduction

This report covers the official Locator workflow only; no name-to-definition arm was run.

- Instances: 8 seeded Lite instances; completed Locator outputs: 8 (1.0).
- Termination: `{'completed': 8}`.
- Official repository evaluator: File=1.0, Class=1.0, Function=0.375, Line=0.625, IoU=0.22718808968808968.
- Paper set-Jaccard adapter: File=1.0, Function=0.6145833333333334.
- Total-token mean/median: 132434.375 / 101599.5; incomplete trajectories: 0.
- LLM-call mean: 6.875; tool-call mean: 6.375; latency mean ms: 123807.0845.
- Tool-output guard: original/returned chars mean 144550.375 / 144550.375; truncated calls mean 0.0; trajectories with truncation 0.
- Experiment-layer 32,000-character guard enabled values: {'False': 8}; all disabled: True.
- Tool usage: {'analyze_file_structure': 4, 'execute_shell_command_with_validation': 1, 'explore_directory': 3, 'extract_complete_method': 8, 'find_class_constructor': 1, 'find_files_containing': 3, 'find_methods_by_name': 8, 'find_variable_usage': 2, 'read_file_lines': 18, 'search_code_with_context': 2, 'show_file_imports': 1}.
- Requested models: {'ep-64pmfvfo': 8}; returned models: {'ep-64pmfvfo': 8}; request IDs recorded/unique/missing: 55/55/0; stop reasons: {'stop': 55}.
- Cost: not reported because qtapi pricing was not supplied.

The official repository metrics are containment booleans, while the paper defines FileAcc/FuncAcc as per-instance Jaccard set similarity; both are retained explicitly.
Predicted ranges were converted to synthetic diff hunks only for calling the upstream evaluator offline; the patch was not provided to the agent.

See `instance_results.jsonl` for every instance, including missing/failure records, and `reproduction_gap_report.md` for implementation/data/evaluation differences.
