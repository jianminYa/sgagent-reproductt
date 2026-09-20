# Full14 / no-N2D configuration diff

This is an offline configuration audit for the same official runner. No paid
no-N2D trajectory was started in Phase3.

| Dimension | full14 | no_n2d | Difference |
|---|---|---|---|
| Runner | `official_locator.py` | `official_locator.py` | none |
| Model / protocol | `ep-64pmfvfo` / OpenAI-compatible Chat Completions | same | none |
| Temperature | `0.0` | `0.0` | none |
| Graph recursion limit | `150` | `150` | none |
| Output policy | raw public return; guard disabled | same | none |
| Retry policy | 3 additional retries; 15/30/60 seconds; 502/503/504 + temporary network errors | same | none |
| Summarizer / workflow / evaluator | unchanged | unchanged | none |
| Enabled tools | 14 | 12 | two removals |

The exact tool-set diff is:

```text
full14 - no_n2d = {
  find_methods_by_name,
  find_all_variables_named,
}
no_n2d - full14 = {}
```

The two names are removed simultaneously from the rendered system-prompt tool
blocks, the official runner's callable registry/tool map, and the trajectory
tool manifest. The remaining common tools include
`find_files_containing`, `search_code_with_context`, `analyze_file_structure`,
`extract_complete_method`, and `read_file_lines`, so related-name tasks retain
multi-step fallback paths.

Offline proof is in `tests/test_phase3_trace_and_arms.py`: it compares the
runner tool sets and prompt blocks and asserts that the set difference is
exactly these two names.
