# Name-to-definition phase-one pilot

Status: real pilot ran; results are pilot evidence only and do not establish a general causal claim.

## Scope

- 45 seeded instances from the exact SWE-Explore ∩ SWE-bench Verified intersection.
- 2 locator-only arms, 90 real `claude-sonnet-5` trajectories.
- Gold locations were parsed offline from the SWE-bench patch; the agent never received the patch.

## Aggregate results

| arm | file accuracy | function accuracy | line hit rate | mean tokens | mean tool calls | incomplete tokens |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 0.022222222222222223 | 0.022222222222222223 | 0 | 71308.46666666666 | 11.666666666666666 | 0 |
| n2d | 0.06666666666666667 | 0.044444444444444446 | 0.06666666666666667 | 72048.65909090909 | 11.622222222222222 | 1 |

N2D lookup recall over all 45 instances: R@1=0.044444444444444446, R@3=0.06666666666666667, R@5=0.08888888888888889; among the 4 instances with a ranked gold candidate: R@1=0.5, R@3=0.75, R@5=1.

## Paired deltas

Deltas are n2d minus baseline; confidence intervals are bootstrap 95% CIs.

- `total_tokens`: mean=773.1818181818181, CI=[-6306.522727272727, 7630.613636363636]
- `locator_llm_calls`: mean=0.022222222222222223, CI=[-0.7111111111111111, 0.6444444444444445]
- `tool_calls`: mean=-0.044444444444444446, CI=[-0.7777777777777778, 0.6222222222222222]
- `file_hit`: mean=0.044444444444444446, CI=[-0.044444444444444446, 0.13333333333333333]
- `function_hit`: mean=0.022222222222222223, CI=[-0.044444444444444446, 0.08888888888888889]
- `max_line_iou`: mean=0.007583774250440917, CI=[0.0, 0.01710758377425044]

Official SWE-Explore scorer fields are intentionally null because the scorer is not bundled in this repository.
See `aggregate_report.json` and `instance_results.csv` for subgroups, tool patterns, contrast examples, and per-instance evidence.
