"""Finish a saved native timeline locally; never regenerate or dub its actors.

Reuses the verified native picture/PCM master, then applies reviewed caption
candidates and source-evidenced audio cleanup. Every export remains a candidate
for complete audiovisual review under the current cinema contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from app.services import studio_native_movie as movie
from app.services import studio_native_media as media


def timeline_identity(plan):
    fields = (
        "shot_id",
        "path",
        "sha256",
        "duration_seconds",
        "source_intervals",
        "dialogue",
        "native_voice_preserved",
        "audio_locale",
    )
    value = [{key: entry.get(key) for key in fields} for entry in plan["shots"]]
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def validate_saved_timeline(source_record, source_plan, plan):
    issues = []
    source = Path(source_record.get("source_native_master", {}).get("path") or "")
    technical = source_record.get("native_technical") or {}
    if not source.is_file() or movie.sha(source) != source_record.get(
        "source_native_master", {}
    ).get("sha256"):
        issues.append("Original native timeline file is missing or changed")
    if source_record.get("media_plan_digest") != movie.media_plan_digest(source_plan):
        issues.append("Original render receipt does not bind the source plan")
    if timeline_identity(source_plan) != timeline_identity(plan):
        issues.append(
            "Caption/sound finishing cannot replace, reorder or retime the native performances"
        )
    seconds = sum(e["duration_seconds"] for e in plan["shots"])
    if (
        technical.get("technical_pass") is not True
        or technical.get("fps") != 24
        or technical.get("fully_decoded_frames") != round(seconds * 24)
    ):
        issues.append("Hash-bound complete native video decode evidence is required")
    return issues


def cleanup_windows(plan, cleanup):
    """All intervals preserve the native sample clock; changing text is forbidden."""
    if not isinstance(cleanup, dict):
        raise ValueError("Cleanup must be a shot-to-evidence mapping")
    known = {entry["shot_id"]: entry for entry in plan["shots"]}
    if set(cleanup) - set(known):
        raise ValueError("Unknown cleanup shot")
    for sid, item in cleanup.items():
        entry = known[sid]
        start, end = (
            item.get("start_seconds", 0),
            item.get("end_seconds", entry["duration_seconds"]),
        )
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or not 0 <= start < end <= entry["duration_seconds"]
            or not item.get("reason")
        ):
            raise ValueError("Cleanup needs bounded native intervals and a reason")
        evidence = Path(item.get("source_review_path") or "")
        if not evidence.is_file() or movie.sha(evidence) != item.get(
            "source_review_sha256"
        ):
            raise ValueError(
                "Cleanup requires preserved hash-bound actual source review"
            )
    return cleanup


def audio_graph(plan, cleanup):
    cleanup_windows(plan, cleanup)
    count = len(plan["shots"])
    labels = "".join(f"[s{i}]" for i in range(count))
    graph = f"[0:a]asplit={count}{labels};"
    offset = 0
    for i, entry in enumerate(plan["shots"]):
        duration = entry["duration_seconds"]
        item = cleanup.get(entry["shot_id"], {})
        total = round(duration * 48000)
        if entry.get("dialogue"):
            start = round(item.get("start_seconds", 0) * 48000)
            end = round(item.get("end_seconds", duration) * 48000)
            samples = end - start
            if samples <= 1800:
                raise ValueError("Native speech cleanup cannot erase the utterance")
            filters = f"atrim=start_sample={offset + start}:end_sample={offset + end},asetpts=PTS-STARTPTS,"
            if item.get("declick") is True:
                filters += "adeclick=w=55:o=75:a=2:t=2:b=2:m=a,"
            filters += f"afade=t=in:ss=0:ns=576,afade=t=out:ss={samples - 1200}:ns=1200,adelay={start}S:all=1,apad=whole_len={total},atrim=end_sample={total}"
        else:
            filters = f"atrim=start_sample={offset}:end_sample={offset + total},asetpts=PTS-STARTPTS,volume=0"
        graph += f"[s{i}]{filters}[a{i}];"
        offset += total
    graph += (
        "".join(f"[a{i}]" for i in range(count)) + f"concat=n={count}:v=0:a=1[voice0];"
    )
    graph += "[voice0]asplit=2[voice][side];"
    seconds = offset / 48000
    graph += f"[1:a]atrim=duration={seconds},asetpts=PTS-STARTPTS[bed];[bed][side]sidechaincompress=threshold=0.04:ratio=8:attack=30:release=350[duck];[voice][duck]amix=inputs=2:normalize=0:duration=first,loudnorm=I=-16:TP=-1.5:LRA=11[a]"
    return graph


def finish_saved_timeline(
    board_path,
    plan_path,
    source_record_path,
    source_plan_path,
    output,
    *,
    music_path,
    music_rights_path,
    cleanup=None,
    caption_font="Arial",
):
    board_path, plan_path, source_record_path, source_plan_path, output = map(
        Path, (board_path, plan_path, source_record_path, source_plan_path, output)
    )
    board = json.loads(board_path.read_text())
    plan = json.loads(plan_path.read_text())
    record = json.loads(source_record_path.read_text())
    source_plan = json.loads(source_plan_path.read_text())
    plan["current_storyboard_file_sha256"] = movie.sha(board_path)
    issues = movie.validate_plan(
        board, plan, require_sequence_review=False
    ) + validate_saved_timeline(record, source_plan, plan)
    if issues:
        raise ValueError("; ".join(issues))
    cleanup = cleanup or {}
    cleanup_windows(plan, cleanup)
    music_path, music_rights_path = map(Path, (music_path, music_rights_path))
    rights = json.loads(music_rights_path.read_text())
    license_path = Path(rights.get("license_evidence_path") or "")
    if (
        rights.get("rights_cleared") is not True
        or movie.sha(music_path) != rights.get("music_sha256")
        or not license_path.is_file()
        or movie.sha(license_path) != rights.get("license_evidence_sha256")
    ):
        raise ValueError(
            "Actual music and cleared hash-bound license evidence are required"
        )
    if (
        not caption_font
        or any(c in caption_font for c in "':,;\\\n")
        or (plan["locale"] != "en" and caption_font == "Arial")
    ):
        raise ValueError("Select a verified locale-covering font")
    if output.exists() or output.with_suffix(".json").exists():
        raise FileExistsError("Keep every previous export and use a new version name")
    output.parent.mkdir(parents=True, exist_ok=True)
    srt, vtt = movie.write_captions(
        plan["shots"],
        output.with_name(output.stem + "_Captions." + plan["locale"]),
        locale=plan["locale"],
    )
    source = Path(record["source_native_master"]["path"])
    duration = sum(s["duration_seconds"] for s in plan["shots"])
    subtitle = (
        str(srt.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    )
    style = f"FontName={caption_font},FontSize=25,PrimaryColour=&H00FFFFFF,OutlineColour=&H00181818,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=30"
    graph = (
        audio_graph(plan, cleanup)
        + f";[0:v]subtitles=filename='{subtitle}':force_style='{style}'[v]"
    )
    media.run_ffmpeg(
        [
            "-i",
            source,
            "-i",
            music_path,
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
            "veryfast",
            "-threads",
            "2",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            output,
        ]
    )
    technical, _ = media.decode_video(
        output,
        expected_frames=round(duration * 24),
        samples={0, round(duration * 24) - 1},
    )
    if not technical["technical_pass"]:
        raise ValueError(
            "Final local export failed technical validation: " + json.dumps(technical)
        )
    import av

    with av.open(str(output)) as container:
        samples = sum(frame.samples for frame in container.decode(audio=0))
    if abs(samples - round(duration * 48000)) > 2048:
        raise ValueError("Final audio sample count changed the native timeline")
    result = {
        "status": "pending_actual_complete_final_movie_av_review",
        "publication_allowed": False,
        "master": {"path": str(output.resolve()), "sha256": movie.sha(output)},
        "duration_seconds": duration,
        "selection_plan": {
            "path": str(plan_path.resolve()),
            "sha256": movie.sha(plan_path),
        },
        "source_native_master": record["source_native_master"],
        "native_technical": record["native_technical"],
        "source_render_receipt": {
            "path": str(source_record_path.resolve()),
            "sha256": movie.sha(source_record_path),
        },
        "source_plan": {
            "path": str(source_plan_path.resolve()),
            "sha256": movie.sha(source_plan_path),
        },
        "media_plan_digest": movie.media_plan_digest(plan),
        "native_timeline_identity": timeline_identity(plan),
        "captions": [
            {"path": str(p.resolve()), "sha256": movie.sha(p)} for p in (srt, vtt)
        ],
        "music": {"path": str(music_path.resolve()), "sha256": movie.sha(music_path)},
        "music_rights": {
            "path": str(music_rights_path.resolve()),
            "sha256": movie.sha(music_rights_path),
        },
        "cleanup": cleanup,
        "technical": technical,
        "final_audio_fully_decoded_samples": samples,
        "new_provider_generations": 0,
        "native_voice_replaced": False,
        "retiming": False,
        "loops_or_still_padding": False,
        "human_review_claim": False,
        "limits": "Actual final-film, caption, acting, continuity and boundary review remain required; technical decode is not creative approval.",
    }
    output.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("board", "plan", "source_record", "source_plan", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--music", required=True, type=Path)
    parser.add_argument("--music-rights", required=True, type=Path)
    parser.add_argument("--cleanup", type=Path)
    parser.add_argument("--caption-font", default="Arial")
    args = parser.parse_args()
    result = finish_saved_timeline(
        args.board,
        args.plan,
        args.source_record,
        args.source_plan,
        args.output,
        music_path=args.music,
        music_rights_path=args.music_rights,
        cleanup=json.loads(args.cleanup.read_text()) if args.cleanup else {},
        caption_font=args.caption_font,
    )
    print(
        json.dumps(
            {
                "master": result["master"],
                "seconds": result["duration_seconds"],
                "publication_allowed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
