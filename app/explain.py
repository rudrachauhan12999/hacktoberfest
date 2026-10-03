"""Two plain sentences that explain a verdict.

The model is given only the rule results, never the label or the photo, so
it can rephrase the verdict but has nothing else to draw on. Its text is
checked in Python before use. Whenever the model is unavailable, breaks a
wording rule, or is not wanted (the user edited numbers or servings), a
template built from the same rule results is used instead.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from . import ollama_client
from .harness import parse_json_object
from .schemas import EXPLANATION_SCHEMA

EXPLAIN_PROMPT = """\
Below are the results of a dietary check on one food, as JSON.
Write a summary of exactly two plain sentences for the person who will eat it.

Rules:
- Use only facts that appear in the JSON. Do not add numbers, ingredients or advice.
- Lead with the most serious result: "fail" before "warn" before "pass".
- Give no medical advice.
- Never say that the food is safe.
- Reply with JSON: {"summary": "..."}
"""

_OPENERS = {
    "green": "This fits your goals for this meal.",
    "amber": "This mostly fits your goals, with a few things to check.",
    "red": "This does not fit your goals.",
}
_FORBIDDEN = re.compile(r"\bsafe(?:ly|ty)?\b", re.IGNORECASE)
_MAX_CHARS = 420


def template_summary(evaluation: dict) -> str:
    """A deterministic summary: the verdict, then the most serious rule's detail."""
    opener = _OPENERS[evaluation["overall"]]
    rules = evaluation.get("rules", [])
    for status in ("fail", "warn"):
        flagged = [rule for rule in rules if rule["status"] == status]
        if flagged:
            first = flagged[0]
            # Allergen and diet details already name their subject; nutrient ones do not.
            named = first["id"].startswith("allergen:") or first["id"] == "diet"
            lead = first["detail"] if named else f"{first['label']}: {first['detail']}"
            text = f"{opener} {lead}"
            if len(flagged) > 1:
                others = ", ".join(rule["label"] for rule in flagged[1:])
                text += f" Also check: {others}."
            return text
    if not rules:
        return "No goals are set to check this against. Add targets in your profile."
    return f"{opener} All {len(rules)} checks passed."


def _acceptable(summary: object) -> Optional[str]:
    if not isinstance(summary, str):
        return None
    text = " ".join(summary.split())
    if not text or len(text) > _MAX_CHARS or _FORBIDDEN.search(text):
        return None
    return text


def explain(evaluation: dict) -> str:
    """Ask the model to phrase the verdict; fall back to the template on any problem."""
    facts = {
        "overall": evaluation["overall"],
        "rules": [
            {"label": rule["label"], "status": rule["status"], "detail": rule["detail"]}
            for rule in evaluation.get("rules", [])
        ],
    }
    message = {
        "role": "user",
        "content": EXPLAIN_PROMPT + "\n" + json.dumps(facts, ensure_ascii=False, indent=1),
    }
    try:
        reply = ollama_client.chat([message], EXPLANATION_SCHEMA)
    except ollama_client.OllamaError:
        return template_summary(evaluation)
    data = parse_json_object(reply) or {}
    return _acceptable(data.get("summary")) or template_summary(evaluation)
