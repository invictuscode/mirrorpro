from __future__ import annotations

import json

import pytest

from app.exercises.library import PRESETS_DIR, ExerciseLibrary
from app.exercises.schema import ExerciseDefinition
from app.feedback.config import DEFAULT_MESSAGES, FeedbackConfig, FormRule, MessageKey, check_wording


@pytest.mark.parametrize(
    "text",
    [
        "This movement is safe.",
        "Safely lower your arm.",
        "No risk of injury.",
        "This will help you heal.",
        "Your diagnosis looks fine.",
        "As prescribed, continue.",
        "Good treatment progress!",
    ],
)
def test_prohibited_wording_is_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="must not make safety, diagnostic or treatment claims"):
        check_wording(text)


def test_length_and_empty_limits() -> None:
    with pytest.raises(ValueError):
        check_wording("   ")
    with pytest.raises(ValueError, match="120"):
        check_wording("x" * 121)


def test_defaults_pass_the_guardrail() -> None:
    for text in DEFAULT_MESSAGES.values():
        check_wording(text)
    assert set(DEFAULT_MESSAGES) == set(MessageKey)


def test_overrides_and_rules_are_checked() -> None:
    with pytest.raises(ValueError):
        FeedbackConfig.model_validate({"messages": {"rep_completed": "Safe and correct!"}})
    with pytest.raises(ValueError):
        FeedbackConfig.model_validate({"messages": {"not_a_key": "Hi"}})
    with pytest.raises(ValueError):
        FormRule(id="bad_rule", joint="elbow_flexion", max_deg=30, message="Keep it safe")


@pytest.mark.parametrize(
    "rule",
    [
        {"id": "no_bounds", "joint": "elbow_flexion", "message": "x"},
        {"id": "inverted", "joint": "elbow_flexion", "min_deg": 50, "max_deg": 20, "message": "x"},
        {"id": "bad_joint", "joint": "tail_wag", "max_deg": 20, "message": "x"},
        {"id": "no_phases", "joint": "elbow_flexion", "max_deg": 20, "phases": [], "message": "x"},
    ],
)
def test_invalid_form_rules(rule: dict) -> None:
    with pytest.raises(ValueError):
        FormRule.model_validate(rule)


def test_config_consistency() -> None:
    rule = {"id": "dup", "joint": "elbow_flexion", "max_deg": 20, "message": "Straighten."}
    with pytest.raises(ValueError, match="unique"):
        FeedbackConfig.model_validate({"form_rules": [rule, rule]})
    with pytest.raises(ValueError, match="min_display_ms"):
        FeedbackConfig(display_ms=1000, min_display_ms=2000)


def test_text_falls_back_to_defaults() -> None:
    cfg = FeedbackConfig.model_validate({"messages": {"too_fast": "Slow down a little."}})
    assert cfg.text(MessageKey.TOO_FAST) == "Slow down a little."
    assert cfg.text(MessageKey.REP_COMPLETED) == DEFAULT_MESSAGES[MessageKey.REP_COMPLETED]


def test_instructions_get_the_wording_guardrail() -> None:
    data = json.loads((PRESETS_DIR / "biceps_curl.json").read_text())
    data["instructions"] = ["This exercise is safe for everyone."]
    with pytest.raises(ValueError, match="safe"):
        ExerciseDefinition.model_validate(data)


def test_presets_load_with_valid_wording_and_most_have_form_rules() -> None:
    # Loading validates every message, rule and instruction against the guardrail.
    lib = list(ExerciseLibrary.from_directory())
    assert sum(1 for d in lib if d.feedback.form_rules) >= len(lib) - 1
