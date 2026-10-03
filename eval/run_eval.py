"""Compare a raw prompt with the full MyThali pipeline on the same model.

Usage, from the project root:

    python eval/run_eval.py                 # every row in eval/labels.csv
    python eval/run_eval.py --limit 3       # the first three rows

Each row of eval/labels.csv names a photo in eval/images/ and gives the values
printed on that label. Two systems read every photo:

    raw       one plain prompt. No JSON schema, no verifier, no retry.
              The reply is parsed as JSON on a best-effort basis.
    pipeline  the app's own path: schema-constrained decoding, the verifier,
              and the retry loop in app/harness.py.

Both use the model named by THALI_MODEL. Results are printed as a markdown
table and written to eval/results.md.

Scoring
    valid JSON       the reply parsed as a JSON object
    field accuracy   share of scored fields that match labels.csv. A number is
                     correct within 5% or 1 unit, whichever is larger. An empty
                     cell means "not printed" and is correct only if the system
                     also reports nothing. Calories and sodium accept the kJ and
                     salt conversions.
    avg attempts     model calls per image (always 1 for raw)
    allergen misses  allergens listed for the label that the system's
                     ingredients, contains and may-contain lists fail to flag
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import extract, harness, ollama_client  # noqa: E402
from app.config import settings  # noqa: E402
from app.knowledge import resolve_allergen  # noqa: E402
from app.verify import label_calories, label_sodium_mg, number  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
NUMERIC_FIELDS = ("serving_size_g", "calories", "protein_g", "carbs_g", "sugar_g", "fat_g", "sodium_mg")
SCORED_FIELDS = ("basis", *NUMERIC_FIELDS)

RAW_PROMPT = """\
Read the nutrition label in this photo and reply with a JSON object with these keys:
product_name, basis ("per_serving" or "per_100g"), serving_size_g, calories, energy_kj,
protein_g, carbs_g, sugar_g, fat_g, fiber_g, sodium_mg, salt_g,
ingredients (list of strings in English), contains (list), may_contain (list).
Use null for a value that is not printed.
"""


@dataclass
class Outcome:
    """One system's reading of one image."""

    data: Optional[dict]
    attempts: int


@dataclass
class Score:
    images: int = 0
    valid_json: int = 0
    fields: int = 0
    fields_correct: int = 0
    attempts: int = 0
    allergens: int = 0
    allergen_misses: int = 0


def run_raw(jpeg: bytes) -> Outcome:
    reply = ollama_client.chat([ollama_client.user_message(RAW_PROMPT, jpeg)], None)
    return Outcome(data=harness.parse_json_object(reply), attempts=1)


def run_pipeline(jpeg: bytes) -> Outcome:
    result = extract.read_label(jpeg)
    return Outcome(data=result.data, attempts=result.attempts)


SYSTEMS = {"raw": run_raw, "pipeline": run_pipeline}


def read_value(data: dict, field: str) -> Optional[float]:
    if field == "calories":
        return label_calories(data)
    if field == "sodium_mg":
        return label_sodium_mg(data)
    return number(data, field)


def number_matches(expected: Optional[float], actual: Optional[float]) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    return abs(actual - expected) <= max(1.0, 0.05 * abs(expected))


def parse_cell(text: str) -> Optional[float]:
    text = (text or "").strip()
    return float(text) if text else None


def split_list(text: str) -> list[str]:
    return [part.strip() for part in (text or "").split(";") if part.strip()]


def strings(value: object) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def score_image(score: Score, row: dict, outcome: Outcome) -> None:
    data = outcome.data
    score.images += 1
    score.attempts += outcome.attempts
    score.valid_json += data is not None

    score.fields += len(SCORED_FIELDS)
    if data is not None:
        score.fields_correct += data.get("basis") == row["basis"].strip()
        for field in NUMERIC_FIELDS:
            score.fields_correct += number_matches(parse_cell(row[field]), read_value(data, field))

    declared = []
    if data is not None:
        for key in ("ingredients", "contains", "may_contain"):
            declared += strings(data.get(key))
    for allergen in split_list(row["allergens"]):
        score.allergens += 1
        flagged = any(group.find(declared) for group in resolve_allergen(allergen))
        score.allergen_misses += not flagged


def percent(part: int, whole: int) -> str:
    return "n/a" if whole == 0 else f"{100 * part / whole:.0f}% ({part}/{whole})"


def render(scores: dict[str, Score], skipped: list[str]) -> str:
    images = next(iter(scores.values())).images
    lines = [
        "# Evaluation results",
        "",
        f"Model `{settings.model}`, {images} label photos, "
        f"run {datetime.now().strftime('%Y-%m-%d %H:%M')}.",
        "",
        "| System | Valid JSON | Field accuracy | Avg attempts | Allergen misses |",
        "|---|---|---|---|---|",
    ]
    names = {"raw": "Raw prompt", "pipeline": "MyThali pipeline"}
    for key, score in scores.items():
        attempts = "n/a" if score.images == 0 else f"{score.attempts / score.images:.2f}"
        misses = "n/a" if score.allergens == 0 else f"{score.allergen_misses} of {score.allergens}"
        lines.append(
            f"| {names[key]} | {percent(score.valid_json, score.images)} "
            f"| {percent(score.fields_correct, score.fields)} | {attempts} | {misses} |"
        )
    lines += [
        "",
        "Field accuracy counts a number as correct within 5% or 1 unit. "
        "An allergen miss is an allergen present on the label that the system did not flag.",
    ]
    if skipped:
        lines += ["", "Skipped (image not found or unreadable): " + ", ".join(skipped) + "."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare a raw prompt with the MyThali pipeline.")
    parser.add_argument("--labels", type=Path, default=EVAL_DIR / "labels.csv")
    parser.add_argument("--images", type=Path, default=EVAL_DIR / "images")
    parser.add_argument("--out", type=Path, default=EVAL_DIR / "results.md")
    parser.add_argument("--limit", type=int, default=None, help="only the first N rows")
    args = parser.parse_args()

    with args.labels.open(newline="", encoding="utf-8-sig") as handle:
        rows = [row for row in csv.DictReader(handle) if (row.get("image") or "").strip()]
    if args.limit is not None:
        rows = rows[:args.limit]
    if not rows:
        print(f"{args.labels} has no data rows. Add one row per photo in {args.images}.")
        return 1

    try:
        ollama_client.require_ready()
    except ollama_client.OllamaError as exc:
        print(exc.message)
        return 1

    scores = {name: Score() for name in SYSTEMS}
    skipped: list[str] = []
    for index, row in enumerate(rows, start=1):
        name = row["image"].strip()
        try:
            jpeg = extract.prepare_image((args.images / name).read_bytes())
        except (OSError, extract.ImageError):
            print(f"[{index}/{len(rows)}] {name}: skipped, image not found or unreadable")
            skipped.append(name)
            continue
        for system, read in SYSTEMS.items():
            try:
                outcome = read(jpeg)
            except ollama_client.OllamaError as exc:
                print(f"Stopped: {exc.message}")
                return 1
            score_image(scores[system], row, outcome)
            state = "no JSON" if outcome.data is None else f"{outcome.attempts} attempt(s)"
            print(f"[{index}/{len(rows)}] {name}: {system} {state}")

    if next(iter(scores.values())).images == 0:
        print("No images could be read, so there is nothing to report.")
        return 1

    report = render(scores, skipped)
    args.out.write_text(report, encoding="utf-8")
    print()
    print(report)
    print(f"Written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
