# Claude-3.5 Full14 baseline reproduction gap report

## Scope and decision

This is the formal, unguarded Full14 Locator-only baseline requested by
`PROMPT_PHASE2_CLAUDE35_BASELINE.md`, updated by Phase3. No N2D arm,
no no-N2D arm, and no paired causal experiment was run.

The API transport and public-tool behavior are validated, and the fixed
8-sample smoke gate passed 8/8. The three persistent Phase2 provider failures
were recovered as new immutable attempt `2` trajectories with request-level
retry and workers=1. The fixed 45-sample baseline is operationally complete
(45/45, provider failure 0/45). The 42 inherited successful trajectories are
legacy traces and do not satisfy the new full sidecar schema; they were not
rerun.

## Reproduction configuration

- Requested model alias: `ep-64pmfvfo`.
- User-provided mapping: this alias maps to Claude-3.5-Sonnet. The API returned the alias itself; no underlying dated model version was inferred.
- Configuration was loaded from a secure local environment configuration, using `OPENAI_BASE_URL` and the credential variable without recording its contents or source path.
- The observed protocol was OpenAI-compatible Chat Completions. Native tools were disabled; the official textual `#TOOL_CALL` protocol was used.
- Full14 prompt, official Locator workflow, `INFO ENOUGH -> PROPOSE LOCATION`, summarizer, recursion limit 150, temperature 0, and Locator-only stopping were retained.
- The experiment-layer 32,000-character guard was disabled. The formal runner returned raw public-tool results to the public `custom_tool_node`; it only recorded original and returned character counts.

The earlier guarded runs were preserved separately as diagnostic artifacts under `*_guarded_diagnostic`; they are not mixed into this report.

## API and output diagnosis

The minimal preflight succeeded with HTTP 200, stop reason `stop`, requested/returned model `ep-64pmfvfo`, and token usage 23 input / 8 output / 31 total. The formal unguarded single sample also succeeded: its largest returned tool body was 435,553 characters, with original and returned sizes equal and no truncation.

Across the selected formal 45 trajectories, original and returned tool character totals are identical; the aggregate report records zero truncated calls and `guard_all_disabled=true`. The largest selected raw tool result was 533,277 characters. No HTTP 400 or context error occurred in the formal run.

The specifically requested `sympy__sympy-15609` trajectory completed successfully. It used 7 tool calls, its largest raw tool result was 5,041 characters, and it had no 400/context error. The known large-output risk was therefore exercised by other instances, including SymPy and Django trajectories, without the experiment-layer guard.

The three Phase3 recovery trajectories recorded 502s only on large-context
logical requests in two samples: matplotlib request body 55,379 chars, and
SymPy request bodies 432,638 and 392,713 chars. Each recovered by retrying the
same logical request body. The third SymPy sample had no 502 in its recovery
attempt. Five public `execute_shell_command_with_validation` tool calls were
recorded as failed tool calls but did not terminate their trajectories; these
are reported separately from provider errors. Hidden shell-validation calls
are traced when they occur; the three recovery trajectories did not invoke
one.

## Metrics and uncertainty

The formal aggregate is in `aggregate_report.json` and includes deterministic percentile bootstrap 95% CIs from 10,000 resamples. The official repository metrics are containment-style evaluator metrics; the paper-style File/Function values are kept as separate set-Jaccard values. Predicted ranges were adapted to synthetic diff hunks only for offline invocation of the upstream evaluator; the patch was never provided to the agent.

Formal baseline point estimates:

- Completion: 45/45 = 1.0000; 95% bootstrap CI [1.0000, 1.0000].
- Official File/Class/Function/Line/IoU: 0.9111 / 0.8222 / 0.3556 / 0.3333 / 0.2235.
- Official metric bootstrap CIs: File [0.8222, 0.9778], Class [0.7111, 0.9333], Function [0.2222, 0.4889], Line [0.2000, 0.4667], IoU [0.1703, 0.2791].
- Paper-style File/Function Jaccard: 0.8593 / 0.5204; CIs [0.7593, 0.9444] / [0.4130, 0.6278].
- Operational and completed-only conditional metrics are identical because all 45 completed. Total tokens: mean 270,819.4, median 98,078, p25 61,481, p75 179,865, p95 1,226,416.4, max 3,660,622; input mean 267,344.2 and output mean 3,475.2.
- Token extremes: highest `sympy__sympy-21379` (3,660,622), then `sympy__sympy-13146` (1,777,554) and `sympy__sympy-21614` (1,417,821); lowest `psf__requests-1963` (12,224).
- Mean calls: Locator 9.98, summarizer 0.82, logical total 10.80, tools 8.49. For the three Phase3 traces, HTTP attempts mean 29.33, successful responses mean 28.33, and request retries mean 1.00; legacy traces do not expose HTTP-attempt fields.
- Tool-return volume across all selected traces: original/returned chars mean 190,070.9 / 190,070.9; among the three Phase3 traces, original/returned bytes mean 1,181,360. No experiment-layer truncation occurred.
- Requested and returned model coverage is 45/45; all 486 observed responses had request IDs and stop reasons. Provider failure is 0/45 = 0%.

## Descriptive comparisons only

Compared with the existing Claude Sonnet 5 Full14 reproduction, this
Claude-3.5 alias run has the current descriptive metrics recorded in
`aggregate_report.json`; this comparison remains non-causal and is not a
Full14 vs no-N2D result.

These are descriptive cross-model observations. They do not identify an N2D causal effect and should not be used as a paired Full14 vs no-N2D conclusion.

The paper's reported File 81.2% and Function 52.4% are not assumed to use exactly the same sample, completion treatment, or evaluator adapter. The current paper-style point estimates (81.48% and 51.30%) are therefore a limited, non-identical comparison only.

## Artifacts

- Connectivity: `connectivity_report.json`.
- Configuration and no-key commands: `config_snapshot.json`.
- Single, smoke, and formal trajectories: the corresponding directories under `experiments/name_to_definition/runs/`.
- Per-instance outputs: `instance_results.jsonl` and `instance_results.csv`.
- Aggregate metrics and bootstrap intervals: `aggregate_report.json` and `aggregate_report.md`.
- Requested tool-instance breakdown: `tool_usage_instance_report.json`.
- Phase3 request-retry diagnosis: `failure_diagnosis.json`.
- Full14/no-N2D offline configuration audit: `full14_no_n2d_config_diff.md`.
- No-key Phase3 configuration snapshot: `phase3_config_snapshot.json`.
- Paired-smoke decision: `phase3_readiness.md`.
