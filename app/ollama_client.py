"""The only module that talks to Ollama.

Two calls are used: /api/chat for the model and /api/tags for the status
check. Every failure is turned into an OllamaError carrying an HTTP status
and a message that tells the user what to do next.
"""

from __future__ import annotations

import base64
from typing import Any, Optional

import httpx

from .config import settings


class OllamaError(Exception):
    """A failed call to Ollama, with the HTTP status the API should return."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _unreachable() -> OllamaError:
    return OllamaError(
        f"Cannot reach Ollama at {settings.ollama_host}. Start it with ollama serve",
        status_code=503,
    )


def _not_installed() -> OllamaError:
    return OllamaError(
        f"Model {settings.model} is not installed. Run ollama pull {settings.model}",
        status_code=503,
    )


def user_message(text: str, image: Optional[bytes] = None) -> dict[str, Any]:
    """Build a user message, attaching a JPEG in Ollama's "images" field."""
    message: dict[str, Any] = {"role": "user", "content": text}
    if image is not None:
        message["images"] = [base64.b64encode(image).decode("ascii")]
    return message


def _error_text(response: httpx.Response) -> str:
    try:
        detail = response.json().get("error")
    except ValueError:
        detail = None
    return str(detail or response.text or response.reason_phrase).strip()


def chat(messages: list[dict[str, Any]], schema: Optional[dict] = None) -> str:
    """Send one chat request and return the model's reply text.

    With a schema, Ollama constrains decoding so the reply is JSON of that
    shape. Temperature is 0 so the same photo gives the same reading.
    """
    payload: dict[str, Any] = {
        "model": settings.model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0},
    }
    if schema is not None:
        payload["format"] = schema

    try:
        response = httpx.post(
            f"{settings.ollama_host}/api/chat",
            json=payload,
            timeout=httpx.Timeout(settings.timeout, connect=settings.health_timeout),
        )
    except httpx.ConnectError as exc:
        raise _unreachable() from exc
    except httpx.TimeoutException as exc:
        raise OllamaError(
            f"Ollama did not answer within {settings.timeout:g} seconds. "
            "The model may still be loading. Try again, or raise THALI_TIMEOUT.",
            status_code=504,
        ) from exc
    except httpx.HTTPError as exc:
        raise OllamaError(f"Ollama request failed: {exc}") from exc

    if response.status_code == 404:
        raise _not_installed()
    if response.status_code >= 400:
        raise OllamaError(
            f"Ollama returned an error ({response.status_code}): {_error_text(response)}"
        )

    try:
        content = response.json()["message"]["content"]
    except (ValueError, KeyError, TypeError) as exc:
        raise OllamaError("Ollama returned a reply that could not be read.") from exc
    if not isinstance(content, str) or not content.strip():
        raise OllamaError("Ollama returned an empty reply.")
    return content


def _is_installed(names: list[str]) -> bool:
    wanted = settings.model if ":" in settings.model else f"{settings.model}:latest"
    return wanted in names


def health() -> dict[str, Any]:
    """Report whether Ollama is reachable and the model is installed. Never raises."""
    status: dict[str, Any] = {
        "host": settings.ollama_host,
        "model": settings.model,
        "reachable": False,
        "model_installed": False,
        "message": None,
    }
    try:
        response = httpx.get(
            f"{settings.ollama_host}/api/tags", timeout=settings.health_timeout
        )
        response.raise_for_status()
        models = response.json().get("models") or []
    except (httpx.HTTPError, ValueError, AttributeError):
        status["message"] = _unreachable().message
        return status

    status["reachable"] = True
    names = [str(model.get("name", "")) for model in models if isinstance(model, dict)]
    status["model_installed"] = _is_installed(names)
    if not status["model_installed"]:
        status["message"] = _not_installed().message
    return status


def require_ready() -> None:
    """Raise a clear OllamaError before a scan if the model cannot be used."""
    status = health()
    if not status["reachable"]:
        raise _unreachable()
    if not status["model_installed"]:
        raise _not_installed()
