"""The verify-and-retry harness, driven by fake chat functions."""

import pytest

from app import harness
from app.ollama_client import OllamaError

from .conftest import FakeChat

MESSAGES = [{"role": "user", "content": "read the label"}]
SCHEMA = {"type": "object"}


def needs_two(data: dict) -> list[str]:
    return [] if data.get("n") == 2 else [f"n is {data.get('n')}, expected 2"]


def test_passes_first_time():
    chat = FakeChat({"n": 2})
    result = harness.run(MESSAGES, SCHEMA, needs_two, chat=chat)
    assert result.ok and result.attempts == 1
    assert result.data == {"n": 2}
    assert result.issues == [] and result.history == [[]]


def test_fails_once_then_succeeds():
    chat = FakeChat({"n": 1}, {"n": 2})
    result = harness.run(MESSAGES, SCHEMA, needs_two, chat=chat, retry_hint="Look again.")

    assert result.ok and result.attempts == 2
    assert result.data == {"n": 2}
    assert result.history == [["n is 1, expected 2"], []]

    # The retry shows the model its own answer and the exact error.
    retry_messages, retry_schema = chat.calls[1]
    assert retry_schema == SCHEMA
    assert [m["role"] for m in retry_messages] == ["user", "assistant", "user"]
    assert retry_messages[1]["content"] == '{"n": 1}'
    assert "- n is 1, expected 2" in retry_messages[2]["content"]
    assert "Look again." in retry_messages[2]["content"]


def test_always_fails_returns_best_attempt():
    def verify(data):
        return [f"problem {i}" for i in range(data["errors"])]

    chat = FakeChat({"errors": 3}, {"errors": 1}, {"errors": 2})
    result = harness.run(MESSAGES, SCHEMA, verify, max_retries=2, chat=chat)

    assert not result.ok
    assert result.attempts == 3
    assert result.data == {"errors": 1}          # fewest errors wins
    assert result.issues == ["problem 0"]
    assert [len(errors) for errors in result.history] == [3, 1, 2]


def test_tie_keeps_the_earlier_attempt():
    chat = FakeChat({"n": 5}, {"n": 6})
    result = harness.run(MESSAGES, SCHEMA, needs_two, max_retries=1, chat=chat)
    assert not result.ok and result.data == {"n": 5}


def test_unparseable_replies_give_no_data():
    chat = FakeChat("not json", "still not json")
    result = harness.run(MESSAGES, SCHEMA, needs_two, max_retries=1, chat=chat)
    assert not result.ok and result.data is None
    assert result.issues == [harness.NOT_JSON]


def test_parsed_attempt_beats_unparsed():
    chat = FakeChat("not json", {"n": 7})
    result = harness.run(MESSAGES, SCHEMA, needs_two, max_retries=1, chat=chat)
    assert result.data == {"n": 7} and result.issues == ["n is 7, expected 2"]


def test_max_retries_zero_calls_once():
    chat = FakeChat({"n": 1})
    result = harness.run(MESSAGES, SCHEMA, needs_two, max_retries=0, chat=chat)
    assert result.attempts == 1 and len(chat.calls) == 1


def test_caller_messages_are_not_modified():
    messages = [{"role": "user", "content": "read"}]
    harness.run(messages, SCHEMA, needs_two, chat=FakeChat({"n": 1}, {"n": 2}))
    assert messages == [{"role": "user", "content": "read"}]


def test_model_errors_are_not_retried():
    def broken(messages, schema=None):
        raise OllamaError("Cannot reach Ollama", status_code=503)

    with pytest.raises(OllamaError):
        harness.run(MESSAGES, SCHEMA, needs_two, chat=broken)


@pytest.mark.parametrize("text, expected", [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": 1}\n```', {"a": 1}),
    ('Here you go: {"a": 1} Hope that helps.', {"a": 1}),
    ("[1, 2]", None),
    ("no braces", None),
    ('{"a": ', None),
])
def test_parse_json_object(text, expected):
    assert harness.parse_json_object(text) == expected
