"""OpenCode JSON 输出的 usage 提取（大纲 L1-A 1.3）。"""

from fleet.executors.opencode import parse_opencode_json_output


def test_extracts_text_and_tokens_from_step_finish():
    stdout = "\n".join(
        [
            '{"type":"step_start","part":{}}',
            '{"type":"text","part":{"type":"text","text":"第一段"}}',
            '{"type":"text","part":{"type":"text","text":"第二段"}}',
            '{"type":"step_finish","part":{"type":"step-finish","tokens":{"total":100,"input":90,"output":10,"reasoning":5,"cache":{"write":0,"read":0}},"cost":0}}',
        ]
    )
    text, usage = parse_opencode_json_output(stdout)
    assert text == "第一段\n第二段"
    assert usage == {
        "prompt_tokens": 90,
        "completion_tokens": 10,
        "reasoning_tokens": 5,
        "total_tokens": 100,
    }


def test_non_json_output_passthrough_without_usage():
    text, usage = parse_opencode_json_output("plain text output")
    assert text == "plain text output"
    assert usage is None


def test_empty_output_returns_empty_without_usage():
    text, usage = parse_opencode_json_output("")
    assert text == ""
    assert usage is None


def test_json_without_tokens_falls_back():
    stdout = '{"type":"text","part":{"type":"text","text":"only text"}}'
    text, usage = parse_opencode_json_output(stdout)
    assert text == "only text"
    assert usage is None
