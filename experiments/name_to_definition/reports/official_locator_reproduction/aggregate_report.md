# Official SGAgent Locator reproduction

This report covers the official Locator workflow only; no name-to-definition arm was run.

- Instances: 45 seeded Lite instances; completed Locator outputs: 45 (1.0).
- Termination: `{'completed': 45}`.
- Official repository evaluator: File=0.9333333333333333, Class=0.9333333333333333, Function=0.4222222222222222, Line=0.26666666666666666, IoU=0.16491006725103774.
- Paper set-Jaccard adapter: File=0.9222222222222223, Function=0.5513227513227513.
- Total-token mean/median: 52088.77777777778 / 41616.0; incomplete trajectories: 0.
- LLM-call mean: 13.311111111111112; tool-call mean: 9.866666666666667; latency mean ms: 191844.21637777778.
- Tool usage: {'execute_shell_command_with_validation': 5, 'explore_directory': 124, 'read_file_lines': 177, 'search_code_with_context': 135, 'show_file_imports': 3}.
- Cost: not reported because qtapi pricing was not supplied.

The official repository metrics are containment booleans, while the paper defines FileAcc/FuncAcc as per-instance Jaccard set similarity; both are retained explicitly.
Predicted ranges were converted to synthetic diff hunks only for calling the upstream evaluator offline; the patch was not provided to the agent.

See `instance_results.jsonl` for every instance, including missing/failure records, and `reproduction_gap_report.md` for implementation/data/evaluation differences.
