from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from app.api.stream_hub import StreamHub
from app.biomechanics import JOINT_ANGLES
from app.pipeline.tracking import TrackingPipeline
from app.pose.topology import CONNECTIONS, LANDMARK_NAMES
from app.schemas.messages import PipelineState, StatusMessage

log = logging.getLogger(__name__)

api = APIRouter(prefix="/api")
ws = APIRouter()


class Health(BaseModel):
    ok: bool


class Topology(BaseModel):
    landmark_names: list[str]
    connections: list[tuple[int, int]]


def _pipeline(request: Request) -> TrackingPipeline:
    return request.app.state.pipeline


@api.get("/health")
def health() -> Health:
    return Health(ok=True)


@api.get("/status")
def get_status(request: Request) -> StatusMessage:
    return _pipeline(request).status()


# Plain `def` (not async): FastAPI runs these in a worker thread, which matters
# because opening the camera blocks for up to a second or two.
@api.post(
    "/camera/start",
    responses={503: {"model": StatusMessage, "description": "Camera or model failed to start"}},
)
def start_camera(request: Request, response: Response) -> StatusMessage:
    result = _pipeline(request).start()
    if result.state is PipelineState.ERROR:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


@api.post("/camera/stop")
def stop_camera(request: Request) -> StatusMessage:
    return _pipeline(request).stop()


@api.get("/pose/topology")
def topology() -> Topology:
    return Topology(landmark_names=list(LANDMARK_NAMES), connections=list(CONNECTIONS))


class AngleDefinition(BaseModel):
    id: str
    label: str
    joint: str
    side: str
    landmarks: tuple[int, int, int] = Field(description="(proximal, vertex, distal) landmark indices")
    convention: str
    description: str


@api.get("/angles/definitions")
def angle_definitions() -> list[AngleDefinition]:
    return [
        AngleDefinition(
            id=d.id,
            label=d.label,
            joint=d.joint,
            side=d.side,
            landmarks=d.landmarks,
            convention=d.convention.value,
            description=d.description,
        )
        for d in JOINT_ANGLES
    ]


@ws.websocket("/ws/stream")
async def stream(websocket: WebSocket) -> None:
    """Server → client stream: JSON status/session (text) and frame packets (binary).
    Clients don't need to send anything; inbound messages are ignored."""
    await websocket.accept()
    hub: StreamHub = websocket.app.state.hub
    pipeline: TrackingPipeline = websocket.app.state.pipeline
    sub = hub.subscribe()

    async def send_loop() -> None:
        # Always start with the current state so the client never guesses.
        # (The hub may hold the same items; skip them to avoid duplicates.)
        sub.mark_seen("status")
        await websocket.send_text(pipeline.status().model_dump_json())
        for initial in websocket.app.state.initial_messages():
            await websocket.send_text(initial)
        while True:
            texts, frame = await sub.next()
            for text in texts:
                await websocket.send_text(text)
            if frame is not None:
                await websocket.send_bytes(frame)

    sender = asyncio.create_task(send_loop())
    # Reading lets us notice a disconnect promptly even while no frames flow.
    receiver = asyncio.create_task(_drain(websocket))
    try:
        done, _ = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                log.warning("WebSocket stream ended with error: %r", exc)
    finally:
        sub.close()
        for task in (sender, receiver):
            task.cancel()


async def _drain(websocket: WebSocket) -> None:
    """Read until the client disconnects."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
