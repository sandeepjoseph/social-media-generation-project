"""Assemble reviewed native performances without a narration replacement.

Every storyboard slot needs an explicitly reviewed, hash-bound moving clip.
Missing shots cannot be filled by loops, stills, a narrator or synthesized voice.
Rendering produces a review candidate, never publishing permission.
"""

from pathlib import Path
import argparse
import hashlib
import json
import math
import textwrap


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def media_plan_digest(plan):
    """Identity of the ordered actual media, timing, words and review evidence."""
    value = {
        key: plan.get(key)
        for key in (
            "storyboard_file_sha256",
            "storyboard_artifact_sha256",
            "flow_bundle_file_sha256",
            "locale",
            "shots",
        )
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def reviewed_caption_cues(entry, *, locale="en"):
    """Validate reviewed local cue times and preserve the utterance exactly once.

    Cue timing comes from the selected performance's word evidence, never from
    stretching the voice or estimating a replacement narration's duration.
    """
    if not entry.get("dialogue"):
        return []
    cues = entry.get("caption_cues")
    if cues is None:
        cues = [
            {
                "start": entry.get("caption_start"),
                "end": entry.get("caption_end"),
                "text": entry["dialogue"],
                "lines": entry.get("caption_lines"),
            }
        ]
    if not isinstance(cues, list) or not cues:
        raise ValueError("Reviewed caption cues must be a nonempty list")
    duration = entry["duration_seconds"]
    result = []
    words = []
    for cue in cues:
        if not isinstance(cue, dict):
            raise ValueError("Each reviewed caption cue must be an object")
        start, end = cue.get("start"), cue.get("end")
        if (
            not all(
                isinstance(x, (int, float))
                and not isinstance(x, bool)
                and math.isfinite(x)
                for x in [start, end]
            )
            or not 0 <= start < end <= duration
            or (result and start < result[-1][1])
        ):
            raise ValueError(
                "Reviewed caption cues must be ordered within the native clip"
            )
        text = cue.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Each reviewed caption cue requires exact text")
        explicit = cue.get("lines")
        if locale != "en" and not explicit:
            raise ValueError(
                "Localized captions require explicitly reviewed line breaks"
            )
        lines = explicit or textwrap.wrap(
            text, 42, break_long_words=False, break_on_hyphens=False
        )
        if (
            not isinstance(lines, list)
            or not 1 <= len(lines) <= 2
            or any(
                not isinstance(line, str)
                or not line.strip()
                or (locale == "en" and len(line) > 42)
                for line in lines
            )
        ):
            raise ValueError(
                "Split the reviewed utterance into word-timed cues; do not shrink captions"
            )
        if " ".join(" ".join(lines).split()) != " ".join(text.split()):
            raise ValueError(
                "Caption lines must preserve the exact localized utterance"
            )
        words.append(text)
        result.append((start, end, "\n".join(lines)))
    if " ".join(" ".join(words).split()) != " ".join(entry["dialogue"].split()):
        raise ValueError("Caption cues must preserve the entire exact utterance once")
    return result


def validate_plan(board, plan, *, require_sequence_review=True, check_readability=True):
    issues = []
    readability = plan.get("caption_readability")
    if isinstance(readability, dict) and readability.get("held"):
        issues.append("Caption readability requires explicit editorial replanning")
    bundle_path = Path(plan.get("flow_bundle_path", ""))
    bundle = {}
    if not bundle_path.is_file() or sha(bundle_path) != plan.get(
        "flow_bundle_file_sha256"
    ):
        issues.append("Current hash-bound Flow bundle is required")
    else:
        bundle = json.loads(bundle_path.read_text())
        if bundle.get("story_id") and plan.get("story_id") != bundle["story_id"]:
            issues.append("Selected plan must bind its own independent story ID")
        if bundle.get("storyboard_sha256") != plan.get("storyboard_artifact_sha256"):
            issues.append("Flow bundle and selected storyboard binding differ")
    locale = plan.get("locale")
    if (
        not isinstance(locale, str)
        or not locale.strip()
        or locale != board.get("locale", "en")
    ):
        issues.append("An explicit matching audio and caption locale is required")
    expected = [s["shot_id"] for s in board["shots"]]
    actual = [s["shot_id"] for s in plan.get("shots", [])]
    if actual != expected:
        issues.append(
            "Selected shots must cover the entire current storyboard in exact order"
        )
    if len(actual) != len(set(actual)):
        issues.append("A storyboard slot cannot repeat")
    total = 0
    origins = []
    for entry in plan.get("shots", []):
        slot = next(
            (s for s in board["shots"] if s["shot_id"] == entry["shot_id"]), None
        )
        if slot is None:
            issues.append("Unknown slot: " + entry["shot_id"])
            continue
        source = Path(entry.get("path", ""))
        if not source.is_file() or sha(source) != entry.get("sha256"):
            issues.append("Missing or changed source: " + entry["shot_id"])
        duration = entry.get("duration_seconds", 0)
        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or not math.isfinite(duration)
            or duration <= 0
        ):
            issues.append("Invalid duration: " + entry["shot_id"])
            continue
        if abs(duration - slot["duration_seconds"]) > 1e-5:
            issues.append(
                "Explicitly replan the selected duration: " + entry["shot_id"]
            )
        frames = duration * 24
        if abs(frames - round(frames)) > 1e-5:
            issues.append("Duration must bind actual native 24fps frames")
        total += duration
        if entry.get("component_review_pass") is not True:
            issues.append("Unreviewed moving component: " + entry["shot_id"])
        review = Path(entry.get("component_review_path", ""))
        if not review.is_file() or sha(review) != entry.get("component_review_sha256"):
            issues.append("Missing or changed component decision: " + entry["shot_id"])
            decision = {}
        else:
            decisions = json.loads(review.read_text())
            decision = next(
                (
                    d
                    for d in decisions.get("shots", [])
                    if d.get("shot_id") == entry["shot_id"]
                    and d.get("asset_sha256") == entry.get("sha256")
                ),
                {},
            )
            if not decision:
                issues.append(
                    "Component decision does not bind this exact asset and slot"
                )
            source_review = Path(decision.get("source_review", ""))
            if not source_review.is_file() or sha(source_review) != decision.get(
                "source_review_sha256"
            ):
                issues.append(
                    "Original audiovisual/context review evidence is missing or changed"
                )
        intervals = entry.get("source_intervals", [])
        if not intervals:
            issues.append(
                "Original frame-interval provenance required: " + entry["shot_id"]
            )
        for interval in intervals:
            key = interval.get("source_sha256")
            original = Path(interval.get("source_path", ""))
            start = interval.get("start_frame")
            end = interval.get("end_frame")
            if (
                not isinstance(key, str)
                or len(key) != 64
                or not isinstance(start, int)
                or not isinstance(end, int)
                or not 0 <= start < end
            ):
                issues.append("Invalid source interval")
                continue
            if not original.is_file() or sha(original) != key:
                issues.append(
                    "Original source interval hash must bind an existing file"
                )
            if any(k == key and max(start, a) < min(end, b) for k, a, b in origins):
                issues.append(
                    "Repeated original footage across selected slots is not permitted"
                )
            origins.append((key, start, end))
        if slot["speech_mode"] == "native_dialogue":
            recipe = next(
                (
                    s
                    for s in bundle.get("shots", [])
                    if s["shot_id"] == entry["shot_id"]
                ),
                {},
            )
            if (
                decision.get("curator_component_pass") is not True
                or decision.get("review_method")
                != "full_utterance_normal_and_half_speed"
            ):
                issues.append("Source-bound native performance approval required")
            if not recipe or decision.get(
                "source_submitted_prompt_sha256"
            ) != recipe.get("prompt_sha256"):
                issues.append(
                    "Native performance does not bind the current exact recipe"
                )
            if entry.get("dialogue") != slot["dialogue"]["text"]:
                issues.append("Script line changed or missing: " + entry["shot_id"])
            if entry.get("native_voice_preserved") is not True:
                issues.append("Native actor voice is required: " + entry["shot_id"])
            if (
                entry.get("audio_locale") != locale
                or entry.get("caption_locale") != locale
            ):
                issues.append("Audio and captions must use the selected locale")
            start, end = entry.get("caption_start"), entry.get("caption_end")
            if (
                not all(
                    isinstance(x, (int, float))
                    and not isinstance(x, bool)
                    and math.isfinite(x)
                    for x in [start, end]
                )
                or not 0 <= start < end <= duration
            ):
                issues.append(
                    "Actual reviewed caption interval required: " + entry["shot_id"]
                )
            try:
                cues = reviewed_caption_cues(entry, locale=locale)
                if check_readability:
                    from app.services.studio_finishing import caption_issues

                    issues.extend(
                        caption_issues(
                            [
                                {
                                    "start_seconds": a,
                                    "end_seconds": b,
                                    "text": text,
                                    "lines": text.splitlines(),
                                }
                                for a, b, text in cues
                            ],
                            locale=locale,
                            expected_text=entry["dialogue"],
                        )
                    )
            except (ValueError, TypeError, KeyError) as exc:
                issues.append(f"Invalid reviewed captions: {entry['shot_id']}: {exc}")
        elif decision.get("context_pass") is not True:
            issues.append("Source-bound contextual action approval required")
    if not 360 <= total <= 480:
        issues.append("The complete children's movie must run 360–480 seconds")
    if (
        not isinstance(plan.get("storyboard_file_sha256"), str)
        or len(plan["storyboard_file_sha256"]) != 64
        or plan.get("storyboard_file_sha256")
        != plan.get("current_storyboard_file_sha256")
    ):
        issues.append("Selected plan is stale")
    if require_sequence_review:
        review_path = Path(plan.get("sequence_review_path") or "")
        if not review_path.is_file() or sha(review_path) != plan.get(
            "sequence_review_sha256"
        ):
            issues.append("Hash-bound whole-sequence audiovisual review is required")
        else:
            review = json.loads(review_path.read_text())
            reviewed_media = Path(review.get("reviewed_media_path", ""))
            if (
                review.get("media_plan_digest") != media_plan_digest(plan)
                or review.get("full_playback_pass") is not True
                or review.get("continuity_pass") is not True
                or review.get("audio_pass") is not True
                or not str(review.get("reviewer", "")).strip()
                or not reviewed_media.is_file()
                or sha(reviewed_media) != review.get("reviewed_media_sha256")
            ):
                issues.append(
                    "Whole-sequence review does not bind this exact movie plan"
                )
    return issues


def timestamp(seconds, decimal=","):
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02}{decimal}{ms:03}"


def write_captions(entries, target, *, locale="en"):
    offset = 0
    cues = []
    for entry in entries:
        cues.extend(
            (offset + a, offset + b, text)
            for a, b, text in reviewed_caption_cues(entry, locale=locale)
        )
        offset += entry["duration_seconds"]
    assert all(
        a < b and (i == 0 or a >= cues[i - 1][1]) for i, (a, b, _) in enumerate(cues)
    )
    srt = Path(str(target) + ".srt")
    vtt = Path(str(target) + ".vtt")
    if srt.exists() or vtt.exists():
        raise FileExistsError("Preserve the prior caption version")
    srt.write_text(
        "\n\n".join(
            f"{i}\n{timestamp(a)} --> {timestamp(b)}\n{text}"
            for i, (a, b, text) in enumerate(cues, 1)
        )
        + "\n",
        encoding="utf-8",
    )
    vtt.write_text(
        "WEBVTT\n\n"
        + "\n\n".join(
            f"{timestamp(a, '.')} --> {timestamp(b, '.')}\n{text}"
            for a, b, text in cues
        )
        + "\n",
        encoding="utf-8",
    )
    return srt, vtt


def render_sequence(entries, target):
    # A single continuous concat keeps PCM sample timing across variable shot
    # lengths; no per-shot AAC padding is concatenated into the movie.
    from app.services.studio_native_media import run_ffmpeg, decode_video

    if target.exists():
        raise FileExistsError("Preserve the prior master version")
    args = []
    filters = []
    for i, entry in enumerate(entries):
        if sha(entry["path"]) != entry["sha256"]:
            raise ValueError("Source changed immediately before render")
        source_check, _ = decode_video(
            entry["path"], expected_frames=round(entry["duration_seconds"] * 24)
        )
        if not source_check["technical_pass"] or not source_check["has_source_audio"]:
            raise ValueError("A native 24fps moving source with audio is required")
        args += ["-threads", "1", "-i", Path(entry["path"])]
        d = entry["duration_seconds"]
        filters += [
            f"[{i}:v]trim=duration={d},settb=AVTB,setpts=PTS-STARTPTS,scale=1280:720,setsar=1,format=yuv420p[v{i}]",
            f"[{i}:a]atrim=duration={d},aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS[a{i}]",
        ]
    filters.append(
        "".join(f"[v{i}][a{i}]" for i in range(len(entries)))
        + f"concat=n={len(entries)}:v=1:a=1[v][a]"
    )
    run_ffmpeg(
        [
            *args,
            "-filter_complex_threads",
            "1",
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-r",
            "24",
            "-c:v",
            "libx264",
            "-crf",
            "17",
            "-preset",
            "fast",
            "-threads",
            "2",
            "-c:a",
            "pcm_s24le",
            target,
        ]
    )
    count = round(sum(e["duration_seconds"] for e in entries) * 24)
    technical, _ = decode_video(
        target, expected_frames=count, samples={0, count // 2, count - 1}
    )
    if not technical["technical_pass"]:
        raise ValueError(technical)
    return technical


def build_native_movie(
    board_path,
    selection_path,
    output,
    *,
    review_cut=False,
    music=None,
    music_rights=None,
    caption_font="Arial",
):
    """Local assembly. Review cuts precede sequence QA; exports never grant release."""
    board_path, selection_path, output = map(Path, (board_path, selection_path, output))
    board = json.loads(board_path.read_text())
    plan = json.loads(selection_path.read_text())
    plan["current_storyboard_file_sha256"] = sha(board_path)
    issues = validate_plan(board, plan, require_sequence_review=not review_cut)
    if issues:
        raise ValueError(
            json.dumps(
                {"status": "held", "issues": issues, "publication_allowed": False}
            )
        )
    rights = None
    if not review_cut:
        if not music or not music_rights:
            raise ValueError("Final sound requires music and its rights evidence")
        music, music_rights = Path(music), Path(music_rights)
        rights = json.loads(music_rights.read_text())
        license_file = Path(rights.get("license_evidence_path", ""))
        if (
            rights.get("music_sha256") != sha(music)
            or rights.get("rights_cleared") is not True
            or not license_file.is_file()
            or sha(license_file) != rights.get("license_evidence_sha256")
        ):
            raise ValueError(
                "Actual music asset and hash-bound rights evidence required"
            )
    if plan["locale"] != "en" and caption_font == "Arial":
        raise ValueError(
            "Choose and verify a font covering the selected caption language"
        )
    if not caption_font or any(x in caption_font for x in "':,;\\\n"):
        raise ValueError("Invalid caption font name")
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = output.with_name(output.stem + "_Native-AV-Review-Candidate.mkv")
    caption_target = output.with_name(output.stem + "_Captions." + plan["locale"])
    for existing in [
        output,
        output.with_suffix(".json"),
        raw,
        Path(str(caption_target) + ".srt"),
        Path(str(caption_target) + ".vtt"),
    ]:
        if existing.exists():
            raise FileExistsError(existing)
    technical = render_sequence(plan["shots"], raw)
    srt, vtt = write_captions(
        plan["shots"],
        caption_target,
        locale=plan["locale"],
    )
    from app.services.studio_native_media import run_ffmpeg, decode_video

    # FFmpeg filter escaping is separate from shell quoting. All I/O uses argv.
    subtitle = (
        str(srt.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    )
    style = f"FontName={caption_font},FontSize=25,PrimaryColour=&H00FFFFFF,OutlineColour=&H00181818,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=30"
    duration = sum(s["duration_seconds"] for s in plan["shots"])
    graph = f"[0:v]subtitles=filename='{subtitle}':force_style='{style}'[v];"
    if review_cut:
        graph += "[0:a]anull[a]"
        extra_inputs = []
    else:
        extra_inputs = ["-i", music]
        graph += f"[0:a]asplit=2[voice][side];[1:a]atrim=duration={duration},asetpts=PTS-STARTPTS[bed];[bed][side]sidechaincompress=threshold=0.04:ratio=8:attack=30:release=350[duck];[voice][duck]amix=inputs=2:normalize=0:duration=first,loudnorm=I=-16:TP=-1.5:LRA=11[a]"
    run_ffmpeg(
        [
            "-i",
            raw,
            *extra_inputs,
            "-filter_complex_threads",
            "1",
            "-filter_complex",
            graph,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-t",
            str(duration),
            "-r",
            "24",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "fast",
            "-threads",
            "2",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            output,
        ]
    )
    final, _ = decode_video(
        output,
        expected_frames=round(duration * 24),
        samples={0, round(duration * 12), round(duration * 24) - 1},
    )
    assert final["technical_pass"]
    record = {
        "status": "pending_actual_whole_movie_av_review",
        "publication_allowed": False,
        "human_review_claim": False,
        "native_voice_replaced": False,
        "retiming": False,
        "loops_or_still_padding": False,
        "duration_seconds": duration,
        "review_cut": review_cut,
        "locale": plan["locale"],
        "media_plan_digest": media_plan_digest(plan),
        "selection_sha256": sha(selection_path),
        "selection_path": str(selection_path.resolve()),
        "storyboard_sha256": sha(board_path),
        "master": {"path": str(output.resolve()), "sha256": sha(output)},
        "source_native_master": {"path": str(raw.resolve()), "sha256": sha(raw)},
        "captions": [{"path": str(p.resolve()), "sha256": sha(p)} for p in [srt, vtt]],
        "music_rights_sha256": sha(music_rights) if rights else None,
        "native_technical": technical,
        "final_technical": final,
        "limits": "Encoding, loudness, and spatial conforming do not establish performance, lip timing, continuity or whole-film editorial approval.",
    }
    output.with_suffix(".json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("board", type=Path)
    parser.add_argument("selection", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review-cut", action="store_true")
    parser.add_argument("--music", type=Path)
    parser.add_argument("--music-rights", type=Path)
    parser.add_argument("--caption-font", default="Arial")
    parser.add_argument(
        "--prepare-readable-captions",
        action="store_true",
        help="Write a new English caption-plan JSON candidate; do not render or approve",
    )
    args = parser.parse_args()
    if args.prepare_readable_captions:
        from app.services.studio_caption_readability import prepare_caption_plan

        if args.output.exists():
            raise FileExistsError("Preserve the prior caption-plan version")
        record = prepare_caption_plan(
            json.loads(args.board.read_text()), json.loads(args.selection.read_text())
        )
        args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "candidate_plan": str(args.output),
                    "publication_allowed": False,
                    "held": record["caption_readability"]["held"],
                },
                indent=2,
            )
        )
        return
    record = build_native_movie(
        args.board,
        args.selection,
        args.output,
        review_cut=args.review_cut,
        music=args.music,
        music_rights=args.music_rights,
        caption_font=args.caption_font,
    )
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
