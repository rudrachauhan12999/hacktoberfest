"""The MyThali API and static file server.

Run with:  uvicorn app.main:app
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy.orm import Session

from . import __version__, db, extract, ollama_client
from .config import DESCRIPTION_MAX_CHARS, STATIC_DIR, settings
from .explain import explain, template_summary
from .harness import HarnessResult
from .rules import evaluate
from .schemas import (
    NUTRIENT_KEYS, EvaluateRequest, Item, LogCreate, LogUpdate, Profile, ProfileOut,
)

# The interactive docs load scripts from a CDN, and this app makes no outside requests.
app = FastAPI(title="MyThali", version=__version__, docs_url=None, redoc_url=None)

RETAKE_MESSAGES = {
    "label": (
        "The label could not be read reliably. Take a sharper, closer photo "
        "with the whole nutrition table in view."
    ),
    "meal": (
        "The meal could not be estimated reliably. Try a clearer photo "
        "or describe the dish in a few words."
    ),
}


# ------------------------------------------------------------------ errors


@app.exception_handler(ollama_client.OllamaError)
def _ollama_error(_request, exc: ollama_client.OllamaError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(RequestValidationError)
def _validation_error(_request, exc: RequestValidationError) -> JSONResponse:
    problems = []
    for error in exc.errors():
        where = ".".join(str(part) for part in error["loc"] if part != "body")
        problems.append(f"{where}: {error['msg']}" if where else error["msg"])
    return JSONResponse(status_code=422, content={"detail": "; ".join(problems)})


# ----------------------------------------------------------------- helpers


def _today() -> str:
    return date.today().isoformat()


def _parse_day(day: Optional[str]) -> str:
    if not day:
        return _today()
    try:
        return date.fromisoformat(day).isoformat()
    except ValueError:
        raise HTTPException(status_code=400, detail="day must look like YYYY-MM-DD")


def _read_upload(upload: UploadFile) -> bytes:
    raw = upload.file.read(settings.max_upload_bytes + 1)
    if len(raw) > settings.max_upload_bytes:
        limit = settings.max_upload_bytes // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"That photo is larger than {limit} MB.")
    return raw


def _prepare(raw: bytes) -> bytes:
    try:
        return extract.prepare_image(raw)
    except extract.ImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _midpoint(rng: Optional[dict]) -> float:
    return 0.0 if not rng else (rng["lo"] + rng["hi"]) / 2


def _day_totals(entries: list[db.LogEntry]) -> dict[str, float]:
    """Midpoint totals of every nutrient across a day's entries."""
    totals = {key: 0.0 for key in NUTRIENT_KEYS}
    for entry in entries:
        entry_totals = ((entry.payload or {}).get("evaluation") or {}).get("totals") or {}
        for key in NUTRIENT_KEYS:
            totals[key] += _midpoint(entry_totals.get(key))
    return {key: round(value, 1) for key, value in totals.items()}


def _targets(profile: Profile) -> dict[str, Optional[float]]:
    return {
        "calories": profile.calories,
        "protein_g": profile.protein_g,
        "carbs_g": profile.carbs_g,
        "fat_g": profile.fat_g,
        "sugar_g": profile.sugar_g_max,
        "sodium_mg": profile.sodium_mg_max,
        "fiber_g": None,
    }


def _scan_response(kind: str, result: HarnessResult, item: Optional[dict],
                   jpeg: Optional[bytes], session: Session) -> dict[str, Any]:
    """Shared tail of both scan endpoints: validate, evaluate, explain."""
    report = {"ok": result.ok, "attempts": result.attempts, "issues": result.issues}
    thumbnail = extract.make_thumbnail(jpeg) if jpeg is not None else None

    if item is not None:
        try:
            item = Item.model_validate(item).model_dump()
        except ValidationError:
            item, report["ok"] = None, False

    if item is None:
        return {
            "needs_retake": True,
            "message": RETAKE_MESSAGES[kind],
            "item": None,
            "evaluation": None,
            "harness": report,
            "explanation": None,
            "thumbnail": thumbnail,
        }

    profile, _ = db.load_profile(session)
    evaluation = evaluate(item, 1.0, profile, db.consumed(session, _today()))
    return {
        "needs_retake": False,
        "item": item,
        "evaluation": evaluation,
        "harness": report,
        "explanation": explain(evaluation),
        "thumbnail": thumbnail,
    }


def _entry_or_404(session: Session, log_id: int) -> db.LogEntry:
    entry = db.get_log(session, log_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="That log entry no longer exists.")
    return entry


# ------------------------------------------------------- health and profile


@app.get("/api/health")
def get_health() -> dict[str, Any]:
    return {"app": "ok", "version": __version__, **ollama_client.health()}


@app.get("/api/profile", response_model=ProfileOut)
def get_profile(session: Session = Depends(db.get_session)) -> ProfileOut:
    profile, configured = db.load_profile(session)
    return ProfileOut(**profile.model_dump(), configured=configured)


@app.put("/api/profile", response_model=ProfileOut)
def put_profile(profile: Profile, session: Session = Depends(db.get_session)) -> ProfileOut:
    db.save_profile(session, profile)
    return ProfileOut(**profile.model_dump(), configured=True)


# ------------------------------------------------------------------- scans


@app.post("/api/scan/label")
def scan_label(image: UploadFile = File(...),
               session: Session = Depends(db.get_session)) -> dict[str, Any]:
    raw = _read_upload(image)
    if not raw:
        raise HTTPException(status_code=400, detail="Add a photo of the nutrition label.")
    jpeg = _prepare(raw)
    ollama_client.require_ready()

    result = extract.read_label(jpeg)
    item = extract.normalise_label(result.data) if result.ok and result.data else None
    return _scan_response("label", result, item, jpeg, session)


@app.post("/api/scan/meal")
def scan_meal(image: Optional[UploadFile] = File(None), description: str = Form(""),
              session: Session = Depends(db.get_session)) -> dict[str, Any]:
    description = " ".join(description.split())
    if len(description) > DESCRIPTION_MAX_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Keep the description under {DESCRIPTION_MAX_CHARS} characters.",
        )
    raw = _read_upload(image) if image is not None else b""
    if not raw and not description:
        raise HTTPException(status_code=400, detail="Add a photo, a description, or both.")
    jpeg = _prepare(raw) if raw else None
    ollama_client.require_ready()

    result = extract.read_meal(jpeg, description)
    item = None
    if result.ok and result.data:
        item = extract.normalise_meal(result.data, has_photo=jpeg is not None)
    return _scan_response("meal", result, item, jpeg, session)


@app.post("/api/evaluate")
def post_evaluate(body: EvaluateRequest,
                  session: Session = Depends(db.get_session)) -> dict[str, Any]:
    """Recompute the verdict after an edit. No model call."""
    day = _today()
    if body.exclude_log_id is not None:
        entry = db.get_log(session, body.exclude_log_id)
        if entry is not None:
            day = entry.day
    profile, _ = db.load_profile(session)
    item = body.item.model_dump()
    evaluation = evaluate(item, body.servings, profile,
                          db.consumed(session, day, exclude_id=body.exclude_log_id))
    return {"item": item, "evaluation": evaluation, "explanation": template_summary(evaluation)}


# --------------------------------------------------------------------- log


@app.get("/api/log")
def get_log(day: Optional[str] = Query(None),
            session: Session = Depends(db.get_session)) -> dict[str, Any]:
    day = _parse_day(day)
    entries = db.list_logs(session, day)
    profile, _ = db.load_profile(session)
    return {
        "day": day,
        "entries": [entry.to_dict() for entry in entries],
        "totals": _day_totals(entries),
        "targets": _targets(profile),
    }


@app.post("/api/log", status_code=201)
def post_log(body: LogCreate, session: Session = Depends(db.get_session)) -> dict[str, Any]:
    day = body.day or _today()
    profile, _ = db.load_profile(session)
    item = body.item.model_dump()
    evaluation = evaluate(item, body.servings, profile, db.consumed(session, day))
    entry = db.add_log(
        session, item=item, servings=body.servings, evaluation=evaluation,
        explanation=body.explanation or template_summary(evaluation),
        thumbnail=body.thumbnail, day=day,
    )
    return entry.to_dict()


@app.put("/api/log/{log_id}")
def put_log(log_id: int, body: LogUpdate,
            session: Session = Depends(db.get_session)) -> dict[str, Any]:
    entry = _entry_or_404(session, log_id)
    profile, _ = db.load_profile(session)
    item = body.item.model_dump()
    evaluation = evaluate(item, body.servings, profile,
                          db.consumed(session, entry.day, exclude_id=entry.id))
    db.update_log(
        session, entry, item=item, servings=body.servings, evaluation=evaluation,
        explanation=body.explanation or template_summary(evaluation),
    )
    return entry.to_dict()


@app.delete("/api/log/{log_id}")
def delete_log(log_id: int, session: Session = Depends(db.get_session)) -> dict[str, Any]:
    entry = _entry_or_404(session, log_id)
    db.delete_log(session, entry)
    return {"deleted": log_id}


# -------------------------------------------------------------------- week


def _streak(days: set[str], today: date) -> int:
    """Consecutive logged days ending today, or yesterday if today is still empty."""
    current = today if today.isoformat() in days else today - timedelta(days=1)
    count = 0
    while current.isoformat() in days:
        count += 1
        current -= timedelta(days=1)
    return count


@app.get("/api/week")
def get_week(day: Optional[str] = Query(None),
             session: Session = Depends(db.get_session)) -> dict[str, Any]:
    """Sunday to Saturday totals for the week containing the given day (default today)."""
    today = date.today()
    anchor = date.fromisoformat(_parse_day(day))
    sunday = anchor - timedelta(days=(anchor.weekday() + 1) % 7)
    week = [sunday + timedelta(days=offset) for offset in range(7)]
    profile, _ = db.load_profile(session)

    by_day: dict[str, list[db.LogEntry]] = {d.isoformat(): [] for d in week}
    for entry in db.logs_between(session, week[0].isoformat(), week[-1].isoformat()):
        by_day[entry.day].append(entry)

    days = []
    for current in week:
        entries = by_day[current.isoformat()]
        totals = _day_totals(entries)
        if not entries:
            status = "none"
        elif profile.calories is None or totals["calories"] <= profile.calories:
            status = "on"
        else:
            status = "off"
        days.append({
            "day": current.isoformat(),
            "weekday": current.strftime("%a"),
            "date": current.day,
            "is_today": current == today,
            "is_future": current > today,
            "entries": len(entries),
            "status": status,
            "totals": totals,
        })

    return {
        "days": days,
        "targets": _targets(profile),
        "streak": _streak(db.logged_days(session), today),
    }


# The web app. Mounted last so the API routes above take priority.
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
