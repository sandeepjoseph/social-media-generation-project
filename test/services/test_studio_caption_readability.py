"""Readability suggestions must preserve reviewed words, timing and release holds."""

import copy
import pytest
from app.services import studio_native_movie as movie
from app.services.studio_caption_readability import prepare_caption_plan
from test.services.test_studio_native_movie import selection as native_selection


@pytest.fixture(name="selection")
def caption_selection(tmp_path):
    return native_selection.__wrapped__(tmp_path)


def test_orphan_cards_merge_without_mutating_reviewed_sources(selection):
    board, plan, _, _ = selection
    entry = plan["shots"][0]
    entry["caption_cues"] = [
        {"start": 0.3, "end": 3.5, "text": "Shall we try this"},
        {"start": 4, "end": 4.4, "text": "together?"},
    ]
    original = copy.deepcopy(plan)
    result = prepare_caption_plan(board, plan)
    assert plan == original
    assert result["shots"][0]["caption_cues"] == [
        {"start": 0.3, "end": 4.4, "text": "Shall we try this together?"}
    ]
    assert (
        result["shots"][0]["source_intervals"]
        == original["shots"][0]["source_intervals"]
    )
    assert result["shots"][0]["sha256"] == original["shots"][0]["sha256"]
    assert not result["caption_readability"]["held"]


def test_existing_pause_extends_card_but_does_not_extend_shot(selection):
    board, plan, _, _ = selection
    plan["shots"][0].update(caption_start=3, caption_end=3.5)
    result = prepare_caption_plan(board, plan)
    assert result["shots"][0]["caption_end"] == 5
    assert result["shots"][0]["duration_seconds"] == 6
    assert result["publication_allowed"] is False
    assert result["sequence_review_path"] is None
    assert movie.validate_plan(board, result)


def test_insufficient_time_is_a_hold_not_stretched_speech(selection):
    board, plan, _, _ = selection
    plan["shots"][0].update(caption_start=5, caption_end=5.8)
    result = prepare_caption_plan(board, plan)
    assert result["shots"][0]["caption_end"] == 5.95
    assert result["shots"][0]["duration_seconds"] == 6
    assert result["caption_readability"]["held"][0]["shot_id"] == "shot-0"
    assert (
        "Caption readability requires explicit editorial replanning"
        in movie.validate_plan(board, result, require_sequence_review=False)
    )


@pytest.mark.parametrize("target", [0, -1, float("nan"), float("inf"), True])
def test_bad_readability_targets_are_rejected(selection, target):
    board, plan, _, _ = selection
    with pytest.raises(ValueError, match="positive finite"):
        prepare_caption_plan(board, plan, chars_per_second=target)


def test_changed_words_are_rejected_before_suggestions(selection):
    board, plan, _, _ = selection
    plan["shots"][0]["dialogue"] = "Different words"
    with pytest.raises(ValueError):
        prepare_caption_plan(board, plan)


def test_localization_never_falls_back_to_english_suggestions(selection):
    board, plan, _, _ = selection
    plan["locale"] = "ml"
    with pytest.raises(ValueError, match="fluent-reviewed"):
        prepare_caption_plan(board, plan)
