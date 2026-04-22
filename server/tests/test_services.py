from app.services import _normalize_tool_call


def test_normalize_tool_call_keeps_raw_string_when_function_arguments_are_not_json() -> None:
    tool_call = {
        'id': 'call-1',
        'function': {
            'name': 'read_file',
            'arguments': "{'path': 'README.md'}",
        },
    }

    normalized = _normalize_tool_call(tool_call)

    assert normalized['toolCallId'] == 'call-1'
    assert normalized['toolName'] == 'read_file'
    assert normalized['toolArgs'] == {'raw': "{'path': 'README.md'}"}

