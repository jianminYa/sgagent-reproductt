# Phase3 completion and paired-smoke readiness

## Recovery result

The three prior provider-failure samples were rerun only as immutable attempt
`2`, with `workers=1`, Full14, no output guard, and request-level retry. All
three completed. The fixed 45-sample offline baseline now reports completion
`45/45` and provider failure `0/45 = 0%`, below the Phase3 2% stop threshold.

The retry evidence is in `failure_diagnosis.json`. Two samples saw 502 on
large-context logical requests and recovered with the same request body; the
third had no 502 in its recovery attempt. No old attempt was deleted or
overwritten.

## Trace status

The three new recovery attempts pass the trace validator, including sidecar
existence/hash checks and summary counter checks. The other 42 selected
successful trajectories were inherited from Phase2 and do not contain the
new per-attempt and sidecar fields. They were intentionally not rerun, as
required by Phase3; the aggregate report labels these as legacy trace gaps.

## Decision

Provider reliability alone satisfies the numerical gate, but the formal
experiment is **not yet cleared for a 10-instance paid paired smoke** because
the fixed baseline as a whole is only 3/45 trace-complete under the new hard
schema. The no-N2D arm is prepared and has offline diff tests, but no paid
no-N2D trajectory was run. A future smoke should begin only after a fresh
smoke manifest is run with this Phase3 runner so every smoke trajectory is
trace-complete; this Phase3 task does not start that experiment.
