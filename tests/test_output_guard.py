from experiments.name_to_definition.output_guard import DEFAULT_MAX_CHARS, protect_tool_output


def test_small_tool_output_is_unchanged_and_audited():
    result = protect_tool_output("read_file_lines", "line 1\nline 2", {"file_path": "pkg/a.py"})
    assert result.text == "line 1\nline 2"
    assert result.original_chars == result.returned_chars
    assert result.truncated is False


def test_large_tool_output_keeps_method_identity_and_location():
    payload = [{
        "absolute_path": "/tmp/repo/pkg/model.py",
        "full_qualified_name": "User.save",
        "content": "def save(self):\n    return self.value\n" + ("# method body\n" * 2000),
        "start_line": 40,
        "end_line": 2042,
        "relationships": {
            "CALLS": [{
                "name": "huge_relation",
                "full_qualified_name": "Other.call",
                "absolute_path": "/tmp/repo/pkg/other.py",
                "start_line": 8,
                "end_line": 12,
                "content": "x" * 200_000,
            }]
        },
    }]
    result = protect_tool_output("extract_complete_method", payload, {"file": "/tmp/repo/pkg/model.py", "full_qualified_name": "User.save"})
    assert result.original_chars > DEFAULT_MAX_CHARS
    assert result.returned_chars <= DEFAULT_MAX_CHARS
    assert result.truncated is True
    assert "User.save" in result.text
    assert "/tmp/repo/pkg/model.py" in result.text
    assert "40" in result.text and "2042" in result.text
    assert "def save(self)" in result.text
    assert "content clipped" in result.text or "relationship bodies were reduced" in result.text
