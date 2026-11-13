"""Fan-out of pipeline output to WebSocket clients.

Producers (worker threads or request handlers) call :meth:`publish_text` /
:meth:`publish_frame`; those store the newest item per channel and wake
subscribers on the event loop. Each subscriber sends only the newest item per
channel it has not yet sent, so a slow client skips stale data instead of
building an unbounded backlog.

Text channels: ``status`` (pipeline state) and ``session`` (exercise session).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass

from app.schemas.messages import StatusMessage

log = logging.getLogger(__name__)


@dataclass(slots=True)
class _Item:
    seq: int
    payload: str | bytes


class Subscription:
    def __init__(self, hub: StreamHub) -> None:
        self._hub = hub
        self._event = asyncio.Event()
        self._text_seqs: dict[str, int] = {}
        self._frame_seq = 0

    def _notify(self) -> None:
        self._event.set()

    async def next(self) -> tuple[list[str], bytes | None]:
        """Wait until there is something new; return (text messages in channel
        order, frame packet or ``None``)."""
        while True:
            texts, frame = self._hub._unseen(self)
            if texts or frame is not None:
                return texts, frame
            self._event.clear()
            # Re-check after clearing to avoid missing a publish in between.
            texts, frame = self._hub._unseen(self)
            if texts or frame is not None:
                return texts, frame
            await self._event.wait()

    def mark_seen(self, channel: str) -> None:
        """Skip the channel's current item (the caller already sent fresher data)."""
        self._hub._mark_seen(self, channel)

    def close(self) -> None:
        self._hub._subscribers.discard(self)


class StreamHub:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._texts: dict[str, _Item] = {}  # insertion order = send order
        self._frame: _Item | None = None
        self._seq = 0
        self._subscribers: set[Subscription] = set()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> Subscription:
        sub = Subscription(self)
        self._subscribers.add(sub)
        return sub

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    # Thread-safe publishers --------------------------------------------------
    def publish_text(self, channel: str, payload: str) -> None:
        with self._lock:
            self._seq += 1
            self._texts[channel] = _Item(self._seq, payload)
        self._wake()

    def publish_status(self, status: StatusMessage) -> None:
        if status.state.value != "running":
            with self._lock:
                # Don't replay a stale frame to clients that connect later.
                self._frame = None
        self.publish_text("status", status.model_dump_json())

    def publish_frame(self, packet: bytes) -> None:
        with self._lock:
            self._seq += 1
            self._frame = _Item(self._seq, packet)
        self._wake()

    def _wake(self) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._notify_all)
        except RuntimeError:
            # Loop closed between the check and the call (during shutdown).
            log.debug("Event loop closed; dropping notification")

    def _notify_all(self) -> None:
        for sub in list(self._subscribers):
            sub._notify()

    def _unseen(self, sub: Subscription) -> tuple[list[str], bytes | None]:
        with self._lock:
            texts: list[str] = []
            for channel, item in self._texts.items():
                if item.seq > sub._text_seqs.get(channel, 0):
                    sub._text_seqs[channel] = item.seq
                    assert isinstance(item.payload, str)
                    texts.append(item.payload)
            frame = None
            if self._frame and self._frame.seq > sub._frame_seq:
                sub._frame_seq = self._frame.seq
                frame = self._frame.payload
        assert frame is None or isinstance(frame, bytes)
        return texts, frame

    def _mark_seen(self, sub: Subscription, channel: str) -> None:
        with self._lock:
            item = self._texts.get(channel)
            if item is not None:
                sub._text_seqs[channel] = item.seq
