# Phase3 trace schema

`trajectory.jsonl` is append-only and flushes every event. Each record carries
the run static metadata, schema version, monotonically increasing `seq`, UTC
timestamp, phase, and event type.

Large complete values are stored under the attempt's `blobs/` directory. A
reference has relative `path`, `sha256`, `chars`, `bytes`, UTF-8 encoding, and
redaction status. Request/response message bodies, HTTP response bodies,
prompt templates, tool returns, summarizer I/O, and shell stdout/stderr use
this form. Authentication headers are never part of the payload or sidecar.

The formal event families are:

- `llm_request`, `llm_http_attempt`, `retry_scheduled`, `llm_response`,
  `llm_error`;
- `nested_llm_request`, `nested_llm_response`, `nested_llm_error`;
- `tool_call`;
- `router_decision`, `graph_update`, `graph_transition`;
- `summarizer_start`, `summarizer_end`, `agent_markers`, `parse_failure`,
  `marker_detected`;
- `kg_build_start`, `kg_build_end`, `run_start`, `run_error`, `final`.

`trace_validator.py` reconstructs request/response pairing, validates tool
results, checks every referenced sidecar's byte count and SHA256, rejects
credential-shaped/config-path content, and recomputes summary counters from
raw events.
