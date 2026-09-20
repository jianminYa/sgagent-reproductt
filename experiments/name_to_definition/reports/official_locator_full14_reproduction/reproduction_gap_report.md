# Full 14-tool SGAgent Locator reproduction gap report

This is the Phase 1B full-tool reproduction requested by
`PROMPT_PHASE1B_FULL_TOOL_REPRODUCE.md`. It measures the official Locator
workflow only; no name-to-definition arm or N2D ablation was run.

## Result and frozen configuration

- Upstream repository: [iSEngLab/SGAgent](https://github.com/iSEngLab/SGAgent)
- Frozen upstream commit: `33a2cfe61d56494ab2d20a2b0c48c1f43e37b452`
- Dataset: local `dataset/lite.parquet`, 300 SWE-bench Lite rows
- Sample: the exact existing 45-instance manifest,
  `random.Random(20260915).sample(sorted(instance_id), 45)`
- Model exception requested by the experiment: `claude-sonnet-5` through the
  local qtapi Anthropic Messages endpoint; the credential was loaded from the
  local environment and was not written to trajectories or reports
- Workflow: official Locator/Suggester/Fixer graph construction, textual
  `#TOOL_CALL` protocol, `INFO ENOUGH -> PROPOSE LOCATION`, official
  summarizer path, and `recursion_limit=150`
- Measurement stop: first parseable Locator output, before Suggester/Fixer

The formal run produced 44/45 latest successful Locator outputs (97.7778%).
The remaining instance, `sympy__sympy-15609`, returned HTTP 400 on two
attempts. The original failed attempts and all retry attempts remain under the
run directory. Every selected trajectory has complete input/output token
accounting; successful API responses have returned model, request ID, and stop
reason metadata.

## The 14-tool prompt correction

The public repository registers 14 tools, but its active public system prompt
describes only five. This reproduction uses the complete tool-description
block represented by the commented section of `prompts/system.py`, in
`experiments/name_to_definition/full_tool_prompt.py`, while leaving tool
semantics unchanged. The prompt render smoke check found all 14 names, and
each run-start manifest exposes all 14 callable schemas:

`analyze_file_structure`, `get_code_relationships`, `find_methods_by_name`,
`extract_complete_method`, `find_class_constructor`, `list_class_attributes`,
`find_variable_usage`, `find_all_variables_named`, `show_file_imports`,
`search_code_with_context`, `find_files_containing`, `explore_directory`,
`read_file_lines`, and `execute_shell_command_with_validation`.

The full-tool prompt is an experiment-local correction; the public active
prompt was not silently rewritten. The runner still uses textual parsing and
the official router rather than native provider tools or a fixed-turn custom
runner.

## Smoke evidence

The fixed 8-instance smoke manifest contains explicit method/class-name cases.
After two transient 524 retries, all 8 latest attempts completed. The smoke
run made four real `find_methods_by_name` calls and no
`find_all_variables_named` calls. Registry inspection, rendered-prompt
inspection, callable signatures, and trajectory parsing all confirmed that the
zero was not caused by missing exposure or an unknown-tool parser failure.
The smoke sample primarily selected structure, method extraction, search, and
file-reading tools; therefore the remaining zero is attributed to model
tool-choice/sample behavior, not to a prompt or parser omission. No special
N2D guidance was added.

## Formal tool usage

The evaluator selects the newest successful attempt per instance. Its selected
formal trajectories contain:

```text
analyze_file_structure                 52
execute_shell_command_with_validation   1
explore_directory                     116
extract_complete_method                 53
find_class_constructor                   1
find_files_containing                   18
find_methods_by_name                   14
find_variable_usage                     1
get_code_relationships                   1
list_class_attributes                    1
read_file_lines                        87
search_code_with_context                41
show_file_imports                        5
find_all_variables_named                 0
failed tool calls                        0
```

Thus both N2D-relevant tools were exposed; `find_methods_by_name` was actually
called, while `find_all_variables_named` remained unused. The raw run,
including retry attempts, contains 15 `find_methods_by_name` calls and still
zero `find_all_variables_named` calls.

## Evaluation and comparison gaps

- The report retains the public repository evaluator's File/Class/Function/
  Line containment booleans and Line IoU.
- It separately reports the paper-style per-instance set Jaccard for File and
  Function. These are not interchangeable metrics.
- The model never receives the gold patch. Predicted ranges are converted to
  synthetic diff hunks only offline so the upstream `PatchParser`,
  `ASTAnalyzer`, and `MetricsCalculator` can be reused.
- The paper reports end-to-end repair on the full Lite benchmark with
  Claude-3.5 and four localization sets per issue. This run is a 45-instance,
  one-trajectory-per-instance Locator measurement with `claude-sonnet-5`, so
  paper headline numbers are not direct apples-to-apples comparisons.
- qtapi pricing was not supplied; cost is intentionally `null`.

The preserved five-tool result is not overwritten. The independent comparison
is in `comparison/comparison_report.md` and compares both metric families,
token/call/latency statistics, and every tool count on the same 45-instance
manifest.

## Environment implementation notes

- The public `agent.core.create_agent` path does not bind native tools in this
  checkout; retaining the textual protocol is therefore part of the official
  reproduction.
- Python 3.13 no longer ships `lib2to3`, while the public AST utility imports
  it. The runner installs a process-local compatibility stub without changing
  normal `ast.parse` behavior.
- The environment uses the available `tree_sitter_language_pack` compatibility
  path rather than the unavailable originally pinned package.
- The retriever is initialized explicitly in each child before workflow use to
  match the effective official timing despite the worktree's lazy-retriever
  changes.
- The official shell-validation tool has a separate nested LLM path if the
  model selects it; outer tool calls and failures are still traced.

See `config_snapshot.json` for the exact commands and runtime snapshot,
`aggregate_report.json`/`.md` for aggregate results, `instance_results.jsonl`
for per-instance evaluation, and the run directory for complete trajectories.
