"""Exercise-session endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import ValidationError

from app.schemas.session import SessionView, StartSession
from app.sessions.manager import SessionConflict, SessionManager, SessionNotFound

router = APIRouter(prefix="/api/session")

_CONFLICT = {409: {"description": "Not allowed in the current session state"}}


def _manager(request: Request) -> SessionManager:
    return request.app.state.sessions


@router.get("")
def get_session(request: Request) -> SessionView | None:
    return _manager(request).view()


@router.post("", responses={404: {"description": "Unknown exercise"}, 422: {"description": "Invalid parameters"}, **_CONFLICT})
def start_session(body: StartSession, request: Request) -> SessionView:
    try:
        return _manager(request).start(body)
    except SessionNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except SessionConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValidationError as exc:
        detail = "; ".join(str(e["msg"]).removeprefix("Value error, ") for e in exc.errors())
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


def _command(request: Request, name: str) -> SessionView:
    try:
        return getattr(_manager(request), name)()
    except SessionConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/pause", responses=_CONFLICT)
def pause(request: Request) -> SessionView:
    return _command(request, "pause")


@router.post("/resume", responses=_CONFLICT)
def resume(request: Request) -> SessionView:
    return _command(request, "resume")


@router.post("/advance", responses=_CONFLICT)
def advance(request: Request) -> SessionView:
    """Finish the current set now, or skip the rest between sets."""
    return _command(request, "advance")


@router.post("/end", responses=_CONFLICT)
def end(request: Request) -> SessionView:
    return _command(request, "end")


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, responses=_CONFLICT)
def dismiss(request: Request) -> Response:
    """Clear a completed or ended session."""
    try:
        _manager(request).dismiss()
    except SessionConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
