from __future__ import annotations

import struct

import pytest

from app.pipeline.metrics import Ema, RateMeter
from app.schemas.messages import FrameMessage, FrameMetrics, decode_frame_packet, encode_frame_packet


def _message(**overrides: object) -> FrameMessage:
    base: dict[str, object] = dict(
        frame_id=7,
        timestamp_ms=1234,
        width=640,
        height=480,
        person_detected=True,
        landmarks=[[0.5, 0.5, 0.0, 0.9, 0.9]] * 33,
        has_preview=True,
        angle_space="image",
        metrics=FrameMetrics(capture_fps=30, inference_fps=29, inference_ms=12.5, latency_ms=20, dropped_frames=1),
    )
    return FrameMessage.model_validate(base | overrides)


def test_frame_packet_round_trip_with_jpeg() -> None:
    jpeg = b"\xff\xd8fake-jpeg\xff\xd9"
    msg, body = decode_frame_packet(encode_frame_packet(_message(), jpeg))
    assert msg == _message()
    assert body == jpeg


def test_frame_packet_without_preview_has_empty_body() -> None:
    msg = _message(has_preview=False, person_detected=False, landmarks=None)
    decoded, body = decode_frame_packet(encode_frame_packet(msg, None))
    assert decoded.landmarks is None
    assert body == b""


@pytest.mark.parametrize("packet", [b"", b"\x00\x00", struct.pack(">I", 999) + b"{}"])
def test_malformed_packets_are_rejected(packet: bytes) -> None:
    with pytest.raises(ValueError):
        decode_frame_packet(packet)


def test_rate_meter_counts_events_in_window() -> None:
    meter = RateMeter(window_s=1.0)
    for i in range(31):
        meter.tick(now=100.0 + i / 30)
    assert meter.rate(now=101.0) == pytest.approx(30.0, rel=0.01)
    # Window slides: everything older than 1 s is forgotten.
    assert meter.rate(now=105.0) == 0.0


def test_ema_starts_at_first_sample_and_smooths() -> None:
    ema = Ema(alpha=0.5)
    assert ema.value is None
    assert ema.update(10) == 10
    assert ema.update(20) == 15
    with pytest.raises(ValueError):
        Ema(alpha=0)
