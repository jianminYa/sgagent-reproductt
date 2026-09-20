# Official SGAgent Locator reproduction gap report

This run is an implementation/data/evaluation consistency reproduction of the
public SGAgent Locator workflow. It is not a claim of exact paper-level
replication, because the paper reports an end-to-end repair experiment.

## Frozen upstream and run configuration

- Upstream remote: `https://github.com/iSEngLab/SGAgent.git`
- Upstream commit: `33a2cfe61d56494ab2d20a2b0c48c1f43e37b452`
- Dataset: local `dataset/lite.parquet`, 300 SWE-bench Lite rows
- Sample: 45 rows, `random.Random(20260915).sample(sorted(instance_id), 45)`
- Model/API exception required by the prompt: `claude-sonnet-5` through the local qtapi Anthropic Messages endpoint
- Official workflow: Locator/Suggester/Fixer graph, static system+locator prompt, textual `#TOOL_CALL`, official KG/tools, recursion limit 150
- Reproduction stopping rule: stop after the first parseable Locator output so Suggester/Fixer are not entered; this is the Locator-only measurement target

## Differences from the paper target

1. The paper's headline result is full end-to-end repair on SWE-bench Lite with
   Claude-3.5, while this run measures only Locator output with
   `claude-sonnet-5`.
2. The paper describes four localization sets per issue for full repair. This
   reproduction records one Locator trajectory per sampled issue.
3. The paper's reported 300-instance results are not directly compared to this
   45-instance pilot. The run reports its own completion, accuracy, usage and
   latency, and keeps per-instance evidence.
4. qtapi pricing was not supplied, so cost is intentionally `null` rather than
   estimated.

## Public-repository implementation gaps

1. The active `prompts/system.py` declares five tools in its prompt, while the
   public `main.py` registers all fourteen tools. The reproduction preserves
   both facts: all fourteen are exposed to the official tool node, and the
   active static prompt is unchanged.
2. The public `agent.core.create_agent` in this checkout does not bind tools;
   the reproduction therefore uses a Runnable without native tool binding and
   preserves the textual `#TOOL_CALL` parser/router path.
3. The public retriever module constructs a global retriever at import time,
   while the current worktree contains a lazy-retriever modification. The
   reproduction explicitly calls `get_retriever()` before importing the
   workflow, restoring the effective official timing for each child process.
4. Python 3.13 has removed `lib2to3`, but the public AST utility imports it.
   The reproduction installs a process-local fallback stub; normal `ast.parse`
   behavior is unchanged, while the obsolete syntax-rewrite fallback remains
   unavailable and is recorded here.
5. The current environment uses the repository's existing
   `tree_sitter_language_pack` compatibility path. The originally pinned
   `tree-sitter-languages` package is unavailable in this environment.
6. The official shell-validation tool contains its own separate hard-coded
   LLM call. If exercised, that nested call is outside the Locator transport;
   its use and result are still captured as an outer tool event.

## Evaluation gaps

- The repository evaluator computes containment booleans for file/class/function
  matches and tolerance-based line matches. The paper defines FileAcc and
  FuncAcc as per-instance Jaccard set similarity. The report emits both metric
  families explicitly.
- The model receives no gold patch. Predicted ranges are converted to
  synthetic diff hunks only offline so the upstream parser/AST/evaluator can be
  reused; this adapter is not part of the agent workflow.

All trajectories, including failures, are retained under the run directory;
`aggregate_report.json`, `aggregate_report.md`, and
`instance_results.jsonl` contain the measured results after the run completes.
