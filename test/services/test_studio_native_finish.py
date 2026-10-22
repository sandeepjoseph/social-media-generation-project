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


def test_normalized_fractional_movie_retains_native_sample_clock(tmp_path):
    """Exercise the real normalizer/resampler, including the final audible tail.

    A 361.125-second release exposed a 2,800-sample AAC shortfall despite a
    correct container duration. Check actual PCM and decoded AAC, not metadata.
    """
    import av
    import numpy as np

    from app.services.studio_native_media import run_ffmpeg

    duration = 361.125
    expected = round(duration * 48000)
    plan = {
        "shots": [
            {
                "shot_id": "native",
                "duration_seconds": duration,
                "dialogue": "Fixture audio, no synthetic actor approval.",
            }
        ]
    }
    pcm = tmp_path / "mixed.wav"
    encoded = tmp_path / "mixed.m4a"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:duration={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=220:sample_rate=48000:duration={duration}",
            "-filter_complex_threads",
            "1",
            "-filter_complex",
            finish.audio_graph(plan, {}),
            "-map",
            "[a]",
            "-c:a",
            "pcm_s24le",
            pcm,
        ]
    )
    with av.open(str(pcm)) as container:
        frames = list(container.decode(audio=0))
    assert sum(frame.samples for frame in frames) == expected
    assert all(frame.sample_rate == 48000 for frame in frames)
    # The end remains audible, rather than satisfying the count with a long
    # silent tail or silently dropping the original performance ending.
    assert np.max(np.abs(frames[-1].to_ndarray().astype(float))) > 0
    run_ffmpeg(["-i", pcm, "-c:a", "aac", "-b:a", "192k", "-t", str(duration), encoded])
    with av.open(str(encoded)) as container:
        decoded_samples = sum(frame.samples for frame in container.decode(audio=0))
    assert abs(decoded_samples - expected) <= 2048


def test_reviewed_non_speaking_room_tone_is_preserved_by_default(tmp_path):
    _, plan, _ = plan_fixture(tmp_path)
    plan["shots"][0].pop("dialogue")
    import av
    import numpy as np
    from app.services.studio_native_media import run_ffmpeg

    plan["shots"][0]["duration_seconds"] = 1
    output = tmp_path / "preserved-native-ambience.wav"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=630:sample_rate=48000:duration=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo:d=1",
            "-filter_complex_threads",
            "1",
            "-filter_complex",
            finish.audio_graph(plan, {}),
            "-map",
            "[a]",
            "-c:a",
            "pcm_f32le",
            output,
        ]
    )
    with av.open(str(output)) as container:
        frames = list(container.decode(audio=0))
    assert sum(frame.samples for frame in frames) == 48000
    # This fails if a silent-action flag erases its real source ambience.
    assert max(float(np.max(np.abs(frame.to_ndarray()))) for frame in frames) > 0.01


def test_explicit_non_dialogue_mute_still_requires_actual_source_evidence(tmp_path):
    _, plan, _ = plan_fixture(tmp_path)
    plan["shots"][0].pop("dialogue")
    with pytest.raises(ValueError, match="hash-bound actual source review"):
        finish.audio_graph(
            plan, {"a": {"mute_non_dialogue": True, "reason": "fixture"}}
        )
    proof = tmp_path / "actual-review.txt"
    proof.write_text("Fixture source evidence, never a real creative approval")
    graph = finish.audio_graph(
        plan,
        {
            "a": {
                "mute_non_dialogue": True,
                "reason": "fixture reviewed unwanted sound",
                "source_review_path": str(proof),
                "source_review_sha256": movie.sha(proof),
            }
        },
    )
    assert "volume=0" in graph


def test_native_actor_dialogue_cannot_be_muted_even_with_a_cleanup_flag(tmp_path):
    _, plan, _ = plan_fixture(tmp_path)
    with pytest.raises(ValueError, match="dialogue cannot be muted"):
        finish.audio_graph(
            plan, {"a": {"mute_non_dialogue": True, "reason": "forbidden"}}
        )
