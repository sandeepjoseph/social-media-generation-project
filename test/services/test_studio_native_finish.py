"""Saved-timeline finishing may alter captions, never native actor timing/order."""

import copy

import pytest

from app.services import studio_native_finish as finish
from app.services import studio_native_movie as movie


def plan_fixture(tmp_path):
    raw = tmp_path / "native.mkv"
    raw.write_bytes(b"Original native timeline hash fixture")
    plan = {
        "locale": "en",
        "shots": [
            {
                "shot_id": "a",
                "path": "native-a.mp4",
                "sha256": "a" * 64,
                "duration_seconds": 6,
                "dialogue": "A complete sentence.",
                "native_voice_preserved": True,
                "audio_locale": "en",
                "caption_start": 0.5,
                "caption_end": 4.5,
                "source_intervals": [{"start_frame": 0, "end_frame": 144}],
            }
        ],
    }
    record = {
        "source_native_master": {"path": str(raw), "sha256": movie.sha(raw)},
        "media_plan_digest": movie.media_plan_digest(plan),
        "native_technical": {
            "technical_pass": True,
            "fps": 24,
            "fully_decoded_frames": 144,
        },
    }
    return raw, plan, record


def test_caption_changes_can_reuse_saved_native_timeline(tmp_path):
    _, plan, record = plan_fixture(tmp_path)
    revised = copy.deepcopy(plan)
    revised["shots"][0]["caption_end"] = 5
    assert finish.validate_saved_timeline(record, plan, revised) == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["shots"][0].update(duration_seconds=7),
        lambda p: p["shots"][0].update(sha256="b" * 64),
        lambda p: p["shots"][0].update(dialogue="Different words"),
        lambda p: p["shots"][0].update(native_voice_preserved=False),
        lambda p: p["shots"][0].update(audio_locale="ml"),
    ],
)
def test_native_performance_changes_require_actual_reassembly_not_cached_pass(
    tmp_path, mutation
):
    _, plan, record = plan_fixture(tmp_path)
    revised = copy.deepcopy(plan)
    mutation(revised)
    assert finish.validate_saved_timeline(record, plan, revised)


def test_timeline_file_tamper_is_rejected(tmp_path):
    raw, plan, record = plan_fixture(tmp_path)
    raw.write_bytes(b"Changed native timeline")
    assert finish.validate_saved_timeline(record, plan, plan)


def test_audio_cleanup_is_source_evidenced_and_sample_clock_bound(tmp_path):
    _, plan, _ = plan_fixture(tmp_path)
    proof = tmp_path / "review.txt"
    proof.write_text("Fixture actual-source review evidence")
    cleanup = {
        "a": {
            "start_seconds": 0.615,
            "end_seconds": 5.5,
            "reason": "Reviewed stray opening/tail fragment",
            "source_review_path": str(proof),
            "source_review_sha256": movie.sha(proof),
        }
    }
    graph = finish.audio_graph(plan, cleanup)
    assert "start_sample=29520:end_sample=264000" in graph
    assert "adelay=29520S:all=1" in graph
    assert "apad=whole_len=288000" in graph
    proof.write_text("Changed evidence")
    with pytest.raises(ValueError, match="hash-bound actual source review"):
        finish.audio_graph(plan, cleanup)


@pytest.mark.parametrize(
    "start,end", [(True, 4), (-1, 4), (0, 7), (5, 4), (float("nan"), 4)]
)
def test_invalid_cleanup_never_erases_or_retimes_a_line(tmp_path, start, end):
    _, plan, _ = plan_fixture(tmp_path)
    with pytest.raises(ValueError, match="bounded native intervals"):
        finish.audio_graph(
            plan, {"a": {"start_seconds": start, "end_seconds": end, "reason": "test"}}
        )
