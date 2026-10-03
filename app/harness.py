"""Verify-and-retry harness around a schema-constrained model call.

A small vision model reading a nutrition label makes mistakes that a schema
cannot catch: a digit dropped from the calories, the sugar and carbohydrate
rows swapped, the per-100g column copied under a per-serving heading. The
JSON is valid; the numbers are impossible.

The harness closes that gap with a loop:

    1. Ask the model for JSON matching the schema.
    2. Parse the reply and pass it to a verifier, a plain Python function
       that returns a list of error messages (empty means acceptable).
    3. If there are errors, show the model its own answer and the exact
       errors, and ask for a corrected JSON. Repeat up to max_retries times.
    4. Return the best attempt, the one with the fewest errors, and say
       whether any attempt passed.

The harness never repairs values itself. When no attempt passes, ok is
False and the caller decides what to do; MyThali asks for a better photo.

It knows nothing about food. The task lives entirely in the three
arguments: the messages, the schema and the verifier.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import ollama_client

Messages = list[dict[str, Any]]
ChatFn = Callable[[Messages, Optional[dict]], str]
VerifyFn = Callable[[dict], list[str]]

NOT_JSON = "The reply was not a JSON object."


@dataclass
class HarnessResult:
    """The outcome of a run.

    data      the best attempt, or None if no reply could be parsed
    ok        True if an attempt passed the verifier
    attempts  how many times the model was called
    issues    the errors of the best attempt (empty when ok)
    history   the errors of every attempt, in order
    """

    data: Optional[dict]
    ok: bool
    attempts: int
    issues: list[str] = field(default_factory=list)
    history: list[list[str]] = field(default_factory=list)


def parse_json_object(text: str) -> Optional[dict]:
    """Parse a reply as a JSON object, tolerating code fences and stray prose."""
    try:
        value = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            value = json.loads(text[start:end + 1])
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def correction_message(errors: list[str], hint: str = "") -> dict[str, str]:
    """The user message that sends the verifier's errors back to the model."""
    lines = ["Your answer has these problems:"]
    lines += [f"- {error}" for error in errors]
    lines.append("")
    if hint:
        lines.append(hint)
    lines.append("Reply with the corrected JSON object only.")
    return {"role": "user", "content": "\n".join(lines)}


def run(
    messages: Messages,
    schema: dict,
    verify: VerifyFn,
    max_retries: int = 2,
    *,
    chat: Optional[ChatFn] = None,
    retry_hint: str = "",
) -> HarnessResult:
    """Call the model until the verifier accepts its answer or retries run out.

    messages     the conversation to send; it is not modified
    schema       JSON schema passed to the model for constrained decoding
    verify       returns a list of error messages for a parsed answer
    max_retries  extra attempts allowed after the first
    chat         the model call, replaceable in tests
    retry_hint   task-specific advice added to each correction request

    Errors raised by the chat function (Ollama unreachable, model missing)
    are not caught: retrying cannot fix them.
    """
    chat = chat or ollama_client.chat
    conversation = list(messages)
    history: list[list[str]] = []
    best_data: Optional[dict] = None
    best_errors: Optional[list[str]] = None

    for attempt in range(1, max_retries + 2):
        reply = chat(conversation, schema)
        data = parse_json_object(reply)
        errors = [NOT_JSON] if data is None else list(verify(data))
        history.append(errors)

        if data is not None and not errors:
            return HarnessResult(data=data, ok=True, attempts=attempt, history=history)

        # Keep the attempt with the fewest errors; a parsed answer always
        # beats an unparsed one, and the earlier answer wins a tie.
        if data is not None and (best_data is None or len(errors) < len(best_errors or [])):
            best_data, best_errors = data, errors
        elif best_errors is None:
            best_errors = errors

        conversation.append({"role": "assistant", "content": reply})
        conversation.append(correction_message(errors, retry_hint))

    return HarnessResult(
        data=best_data,
        ok=False,
        attempts=len(history),
        issues=best_errors or [],
        history=history,
    )
