"""Native assembly must fail closed on changed evidence, timing or locale."""

import copy
import json

import pytest

from app.services import studio_native_movie as movie
from app.services import studio_cinema as cinema
from test.services.test_studio_cinema import film


def document(path, value):
    path.write_text(json.dumps(value))
    return str(path), movie.sha(path)


@pytest.fixture
def selection(tmp_path):
    board = {"locale": "en", "shots": []}
    plan = {"locale": "en", "shots": []}
    recipes, decisions = [], []
    evidence, evidence_sha = document(
        tmp_path / "review.json", {"method": "test fixture"}
    )
    for i in range(60):
        sid = f"shot-{i}"
        path = tmp_path / f"source-{i}.mp4"
        path.write_bytes(f"unique fixture {i}".encode())
        asset_sha = movie.sha(path)
        prompt_sha = cinema.digest({"shot": sid})
        board["shots"].append(
            {
                "shot_id": sid,
                "duration_seconds": 6,
                "speech_mode": "native_dialogue",
                "dialogue": {"text": "Shall we try this together?"},
            }
        )
        recipes.append({"shot_id": sid, "prompt_sha256": prompt_sha})
        decisions.append(
            {
                "shot_id": sid,
                "asset_sha256": asset_sha,
                "source_review": evidence,
                "source_review_sha256": evidence_sha,
                "curator_component_pass": True,
                "review_method": "full_utterance_normal_and_half_speed",
                "sync_observations": [
                    {
                        "seconds": t,
                        "visible_and_audible_event": f"Fixture observed event {t}",
                    }
                    for t in (0.5, 2.5, 4.5)
                ],
                "source_submitted_prompt_sha256": prompt_sha,
            }
        )
        plan["shots"].append(
            {
                "shot_id": sid,
                "path": str(path),
                "sha256": asset_sha,
                "duration_seconds": 6,
                "component_review_pass": True,
                "source_intervals": [
                    {
                        "source_path": str(path),
                        "source_sha256": asset_sha,
                        "start_frame": 0,
                        "end_frame": 144,
                    }
                ],
                "dialogue": "Shall we try this together?",
                "native_voice_preserved": True,
                "audio_locale": "en",
                "caption_locale": "en",
                "caption_start": 0.3,
                "caption_end": 5.1,
            }
        )
    board_path, board_sha = document(tmp_path / "board.json", board)
    plan.update(
        storyboard_file_sha256=board_sha,
        current_storyboard_file_sha256=board_sha,
        storyboard_artifact_sha256=cinema.digest(board),
    )
    path, file_sha = document(
        tmp_path / "bundle.json",
        {"storyboard_sha256": cinema.digest(board), "shots": recipes},
    )
    plan.update(flow_bundle_path=path, flow_bundle_file_sha256=file_sha)
    path, file_sha = document(tmp_path / "decisions.json", {"shots": decisions})
    for entry in plan["shots"]:
        entry.update(component_review_path=path, component_review_sha256=file_sha)
    return board, plan, tmp_path, board_path


def test_review_cut_allows_pending_sequence_but_never_skips_component_checks(selection):
    board, plan, _, _ = selection
    assert movie.validate_plan(board, plan, require_sequence_review=False) == []
    assert (
        "Hash-bound whole-sequence audiovisual review is required"
        in movie.validate_plan(board, plan)
    )
    plan["shots"][0]["component_review_pass"] = False
    assert any(
        "Unreviewed moving component" in x
        for x in movie.validate_plan(board, plan, require_sequence_review=False)
    )


@pytest.mark.parametrize("bad", ["0.5", "0.5-1.0", True, float("nan"), -1, 7])
def test_invalid_component_observations_block_before_render(selection, bad):
    board, plan, _, _ = selection
    from pathlib import Path

    path = Path(plan["shots"][0]["component_review_path"])
    decisions = json.loads(path.read_text())
    decisions["shots"][0]["sync_observations"][0]["seconds"] = bad
    _, digest = document(path, decisions)
    for entry in plan["shots"]:
        entry["component_review_sha256"] = digest
    assert any(
        "invalid_sync_observation" in issue
        for issue in movie.validate_plan(board, plan, require_sequence_review=False)
    )


def test_duplicate_component_observation_times_block_before_render(selection):
    board, plan, _, _ = selection
    from pathlib import Path

    path = Path(plan["shots"][0]["component_review_path"])
    decisions = json.loads(path.read_text())
    for observation in decisions["shots"][0]["sync_observations"]:
        observation["seconds"] = 1
    _, digest = document(path, decisions)
    for entry in plan["shots"]:
        entry["component_review_sha256"] = digest
    assert any(
        "distinct_sync_observations_required" in issue
        for issue in movie.validate_plan(board, plan, require_sequence_review=False)
    )


@pytest.mark.parametrize(
    "change, expected",
    [
        (lambda p: p["shots"].reverse(), "exact order"),
        (lambda p: p["shots"][0].update(duration_seconds=5.5), "replan"),
        (lambda p: p["shots"][0].update(dialogue="Replacement speech"), "Script line"),
        (lambda p: p["shots"][0].update(caption_end=8), "caption interval"),
        (
            lambda p: p["shots"][0].update(native_voice_preserved=False),
            "Native actor voice",
        ),
        (lambda p: p["shots"][0].update(audio_locale="ml"), "selected locale"),
        (lambda p: p.update(current_storyboard_file_sha256="0" * 64), "stale"),
    ],
)
def test_changed_plan_is_held(selection, change, expected):
    board, plan, _, _ = selection
    change(plan)
    assert any(
        expected in x
        for x in movie.validate_plan(board, plan, require_sequence_review=False)
    )


def test_tampered_source_or_review_is_held(selection):
    board, plan, _, _ = selection
    entry = plan["shots"][0]
    from pathlib import Path

    Path(entry["path"]).write_bytes(b"changed video")
    assert any(
        "changed source" in x
        for x in movie.validate_plan(board, plan, require_sequence_review=False)
    )
    Path(entry["component_review_path"]).write_text("{}")
    assert any(
        "changed component decision" in x
        for x in movie.validate_plan(board, plan, require_sequence_review=False)
    )


def test_a_new_slot_cannot_repeat_the_same_original_frames(selection):
    board, plan, _, _ = selection
    plan["shots"][1]["source_intervals"] = copy.deepcopy(
        plan["shots"][0]["source_intervals"]
    )
    assert any(
        "Repeated original footage" in x
        for x in movie.validate_plan(board, plan, require_sequence_review=False)
    )


def test_silent_reaction_cannot_cover_a_broken_native_speaking_take(selection):
    board, plan, _, _ = selection
    entry = plan["shots"][0]
    original = copy.deepcopy(entry["source_intervals"][0])
    reaction = copy.deepcopy(plan["shots"][1]["source_intervals"][0])
    original["end_frame"] = 120
    reaction.update(start_frame=0, end_frame=24)
    entry["source_intervals"] = [original, reaction]
    assert any(
        "one continuous original A/V source" in issue
        for issue in movie.validate_plan(board, plan, require_sequence_review=False)
    )


def test_splicing_restarted_words_from_one_take_still_requires_reshoot(selection):
    board, plan, _, _ = selection
    original = plan["shots"][0]["source_intervals"][0]
    plan["shots"][0]["source_intervals"] = [
        {**original, "end_frame": 60},
        {**original, "start_frame": 72},
    ]
    assert any(
        "one continuous original A/V source" in issue
        for issue in movie.validate_plan(board, plan, require_sequence_review=False)
    )


def test_native_source_interval_cannot_hide_picture_clock_mismatch(selection):
    board, plan, _, _ = selection
    plan["shots"][0]["source_intervals"][0]["end_frame"] = 145
    assert any(
        "original frame clock" in issue
        for issue in movie.validate_plan(board, plan, require_sequence_review=False)
    )


def test_sequence_pass_binds_exact_ordered_media_and_reviewed_movie(selection):
    board, plan, folder, _ = selection
    reviewed = folder / "actual-review-cut.mp4"
    reviewed.write_bytes(b"reviewed audiovisual candidate fixture")
    path, file_sha = document(
        folder / "sequence.json",
        {
            "reviewer": "Fixture independent reviewer",
            "full_playback_pass": True,
            "continuity_pass": True,
            "audio_pass": True,
            "media_plan_digest": movie.media_plan_digest(plan),
            "reviewed_media_path": str(reviewed),
            "reviewed_media_sha256": movie.sha(reviewed),
        },
    )
    plan.update(sequence_review_path=path, sequence_review_sha256=file_sha)
    assert movie.validate_plan(board, plan) == []
    plan["shots"][0]["caption_start"] = 0.5
    assert any("exact movie plan" in x for x in movie.validate_plan(board, plan))


def test_localized_captions_cannot_silently_fall_back_to_english(tmp_path):
    entry = {
        "dialogue": "നമുക്ക് ഒരുമിച്ച് ശ്രമിക്കാം.",
        "duration_seconds": 6,
        "caption_start": 0.3,
        "caption_end": 4.9,
    }
    with pytest.raises(ValueError, match="reviewed line breaks"):
        movie.write_captions([entry], tmp_path / "ml", locale="ml")
    entry["caption_lines"] = [entry["dialogue"]]
    srt, _ = movie.write_captions([entry], tmp_path / "ml", locale="ml")
    assert entry["dialogue"] in srt.read_text()


def test_editorial_duration_does_not_change_provider_take_or_invent_a_stretch():
    script, board = film()
    shot = board["shots"][0]
    shot.update(
        duration_seconds=5.166666666666667,
        provider_take_duration_seconds=6,
        native_editorial_plan={
            "original_av_timing_preserved": True,
            "retiming": False,
            "voice_replacement": False,
            "provenance_sha256": "a" * 64,
        },
    )
    assert cinema.storyboard_issues(board, script, cinema.DEFAULTS) == []
    shot["native_editorial_plan"]["retiming"] = True
    assert any(
        "native_edit_provenance_required" in x
        for x in cinema.storyboard_issues(board, script, cinema.DEFAULTS)
    )


def test_long_native_line_uses_reviewed_word_timed_cues_without_changing_words(
    tmp_path,
):
    entry = {
        "dialogue": "A beautiful idea needs careful thought. Let us listen to each other and build it together.",
        "duration_seconds": 8,
        "caption_start": 0.4,
        "caption_end": 7.5,
        "caption_cues": [
            {
                "start": 0.4,
                "end": 3.1,
                "text": "A beautiful idea needs careful thought.",
            },
            {
                "start": 3.2,
                "end": 7.5,
                "text": "Let us listen to each other and build it together.",
            },
        ],
    }
    srt, vtt = movie.write_captions([entry], tmp_path / "long.en")
    assert "00:00:00,400 --> 00:00:03,100" in srt.read_text()
    assert "00:00:03.200 --> 00:00:07.500" in vtt.read_text()
    assert len(movie.reviewed_caption_cues(entry)) == 2
    with pytest.raises(FileExistsError):
        movie.write_captions([entry], tmp_path / "long.en")


@pytest.mark.parametrize(
    "cue_change",
    [
        {"start": True},
        {"start": -1},
        {"end": float("nan")},
        {"end": 8.1},
        {"text": "We tried again."},
        {"lines": ["Wrong words"]},
        {"lines": ["We", "try", "together."]},
    ],
)
def test_invalid_subcues_are_held_before_render(selection, cue_change):
    board, plan, _, _ = selection
    entry = plan["shots"][0]
    cue = {"start": 0.3, "end": 5.1, "text": entry["dialogue"]}
    cue.update(cue_change)
    entry["caption_cues"] = [cue]
    assert any(
        "Invalid reviewed captions" in issue
        for issue in movie.validate_plan(board, plan, require_sequence_review=False)
    )


def test_subcues_cannot_overlap_repeat_omit_or_fall_back_in_another_language():
    entry = {
        "dialogue": "Try this together.",
        "duration_seconds": 6,
        "caption_cues": [
            {"start": 0.3, "end": 2, "text": "Try this"},
            {"start": 1.9, "end": 4, "text": "together."},
        ],
    }
    with pytest.raises(ValueError, match="ordered"):
        movie.reviewed_caption_cues(entry)
    entry["caption_cues"][1]["start"] = 2.1
    entry["caption_cues"][1]["text"] = "this together."
    with pytest.raises(ValueError, match="entire exact utterance once"):
        movie.reviewed_caption_cues(entry)
    entry["caption_cues"][1]["text"] = "together."
    with pytest.raises(ValueError, match="reviewed line breaks"):
        movie.reviewed_caption_cues(entry, locale="ml")
    for cue in entry["caption_cues"]:
        cue["lines"] = [cue["text"]]
    assert len(movie.reviewed_caption_cues(entry, locale="ml")) == 2


def test_mixed_length_and_audio_layouts_keep_native_frame_and_pcm_timing(tmp_path):
    av = pytest.importorskip(
        "av", reason="Native media integration requires the media runtime"
    )
    from app.services.studio_native_media import run_ffmpeg

    entries = []
    for i, (duration, rate, channels) in enumerate([(1, 44100, 1), (1.5, 48000, 2)]):
        source = tmp_path / f"synthetic-{i}.mp4"
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"testsrc2=size=1280x720:rate=24:duration={duration}",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:sample_rate={rate}:duration={duration}",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-threads",
                "1",
                "-c:a",
                "aac",
                "-ac",
                str(channels),
                "-shortest",
                source,
            ]
        )
        entries.append(
            {
                "path": str(source),
                "sha256": movie.sha(source),
                "duration_seconds": duration,
            }
        )
    target = tmp_path / "timed-native.mkv"
    result = movie.render_sequence(entries, target)
    assert result["fully_decoded_frames"] == 60
    assert result["frame_duration_seconds"] == 2.5
    assert result["technical_pass"] is True
    with av.open(str(target)) as container:
        audio = container.streams.audio[0]
        assert audio.codec_context.name == "pcm_s24le"
        assert len(audio.codec_context.layout.channels) == 2
        samples = sum(frame.samples for frame in container.decode(audio=0))
        assert samples == 120000
    with pytest.raises(FileExistsError):
        movie.render_sequence(entries, target)
