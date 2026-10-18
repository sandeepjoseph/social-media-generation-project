"""Opt-in film performance contracts. Checks never infer lip sync from ASR.

The public implementation is reusable; brand choices and learning rules remain
in the external profile. Existing frozen projects keep their original contract
until explicitly replanned.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "2.1.0"
DEFAULTS = {
    "enabled": True,
    "mode": "dialogue_led_film",
    "full_episode_min_seconds": 360,
    "full_episode_max_seconds": 480,
    "max_narrator_word_fraction": 0.20,
    "min_dialogue_duration_fraction": 0.55,
    "min_performance_duration_fraction": 0.75,
    "min_speaking_characters": 2,
    "max_dialogue_words_per_second": 2.5,
    "dialogue_handle_seconds": 1.0,
}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def policy_for(profile: dict) -> dict:
    configured = profile.get("cinema_policy") or {}
    if configured.get("enabled") is not True:
        return {}
    policy = {**DEFAULTS, **configured, "contract_version": CONTRACT_VERSION}
    for key in DEFAULTS:
        if key in {"enabled", "mode"}:
            continue
        value = policy[key]
        if not finite_number(value) or value < 0:
            raise ValueError(f"invalid cinema policy: {key}")
        if "fraction" in key and value > 1:
            raise ValueError(f"cinema fraction outside 0..1: {key}")
    if (
        policy["full_episode_min_seconds"] <= 0
        or policy["full_episode_min_seconds"] > policy["full_episode_max_seconds"]
        or policy["min_speaking_characters"] < 1
        or int(policy["min_speaking_characters"]) != policy["min_speaking_characters"]
    ):
        raise ValueError("invalid cinema duration or character policy")
    if policy["mode"] != "dialogue_led_film":
        raise ValueError("unsupported cinema performance mode")
    return policy


def implementation_identity(repo: Path) -> dict:
    """Content identity also detects an uncommitted implementation change."""
    files = (
        "app/services/studio_cinema.py",
        "app/services/story_studio.py",
        "webui/pages/2_Director_Studio.py",
        "app/services/studio_native_movie.py",
        "app/services/studio_native_media.py",
    )
    hashes = {
        name: hashlib.sha256((repo / name).read_bytes()).hexdigest()
        if (repo / name).is_file()
        else "missing"
        for name in files
    }
    try:
        revision = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        revision = "unavailable"
    return {
        "contract_version": CONTRACT_VERSION,
        "git_revision": revision,
        "implementation_sha256": digest(hashes),
    }


def duration_issues(seconds: Any, policy: dict, label: str) -> list[str]:
    if not policy:
        return []
    if not finite_number(seconds):
        return [f"cinema:{label}_duration_unverified"]
    if not (
        policy["full_episode_min_seconds"] - 0.25
        <= seconds
        <= policy["full_episode_max_seconds"] + 0.25
    ):
        return [f"cinema:{label}_outside_full_episode_duration"]
    return []


def screenplay_issues(document: dict, policy: dict) -> list[str]:
    if not policy:
        return []
    issues = []
    roles = {
        r.get("role_id"): r for r in document.get("roles", []) if isinstance(r, dict)
    }
    if any(r.get("kind") not in {"character", "narrator"} for r in roles.values()):
        issues.append("cinema:explicit_character_or_narrator_kind_required")
    words = narrator_words = 0
    speaking = set()
    line_ids = set()
    total_duration = 0.0
    beats = set()
    for scene in document.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        if (
            not str(scene.get("action", "")).strip()
            or not str(scene.get("dramatic_purpose", "")).strip()
        ):
            issues.append("cinema:scene_needs_action_and_dramatic_purpose")
        beats.add(scene.get("story_beat"))
        duration = scene.get("estimated_duration_seconds")
        if not finite_number(duration) or duration <= 0:
            issues.append("cinema:scene_duration_required")
        else:
            total_duration += duration
        for line in scene.get("lines", []):
            if not isinstance(line, dict):
                continue
            lid = line.get("line_id")
            if not isinstance(lid, str) or not lid.strip() or lid in line_ids:
                issues.append("cinema:unique_line_id_required")
            line_ids.add(lid) if isinstance(lid, str) else None
            role_id = line.get("role_id")
            count = len(str(line.get("text", "")).split())
            words += count
            if roles.get(role_id, {}).get("kind") == "narrator":
                narrator_words += count
            elif roles.get(role_id, {}).get("kind") == "character":
                speaking.add(role_id)
                if not str(roles[role_id].get("voice_id", "")).strip():
                    issues.append("cinema:character_voice_identity_required")
    if words == 0 or narrator_words / words > policy["max_narrator_word_fraction"]:
        issues.append("cinema:narration_dominates_character_dialogue")
    if len(speaking) < policy["min_speaking_characters"]:
        issues.append("cinema:too_few_speaking_characters")
    if not {"setup", "problem", "attempt", "turn", "resolution"}.issubset(beats):
        issues.append("cinema:complete_dramatic_arc_required")
    issues.extend(duration_issues(total_duration, policy, "screenplay"))
    return sorted(set(issues))


def storyboard_issues(board: dict, screenplay: dict, policy: dict) -> list[str]:
    if not policy:
        return []
    issues = []
    roles = {r["role_id"]: r for r in screenplay.get("roles", [])}
    lines = {
        line.get("line_id"): (scene.get("scene_id"), line)
        for scene in screenplay.get("scenes", [])
        for line in scene.get("lines", [])
    }
    seen = set()
    total = dialogue_duration = performance_duration = 0.0
    for shot in board.get("shots", []):
        if not isinstance(shot, dict):
            continue
        sid = shot.get("shot_id", "unknown")
        mode = shot.get("speech_mode")
        if mode not in {
            "native_dialogue",
            "character_action",
            "narration",
            "establishing",
        }:
            issues.append(f"cinema:{sid}:speech_mode_required")
        for field in (
            "camera",
            "lighting",
            "weather",
            "action_start",
            "action_end",
            "emotional_direction",
            "eyeline",
            "costume_state",
            "continuity",
            "transition",
        ):
            if not shot.get(field):
                issues.append(f"cinema:{sid}:{field}_required")
        duration = shot.get("duration_seconds")
        if not finite_number(duration) or duration <= 0:
            continue  # The base storyboard validator reports this.
        total += duration
        if mode in {"native_dialogue", "character_action"}:
            performance_duration += duration
            if not any(
                roles.get(r, {}).get("kind") == "character"
                for r in shot.get("roles", [])
            ):
                issues.append(f"cinema:{sid}:visible_character_required")
        if mode not in {"native_dialogue", "narration"}:
            if shot.get("dialogue"):
                issues.append(f"cinema:{sid}:speech_in_silent_shot")
            continue
        speech = shot.get("dialogue")
        if not isinstance(speech, dict):
            issues.append(f"cinema:{sid}:exact_dialogue_required")
            continue
        lid = speech.get("line_id")
        if not isinstance(lid, str) or lid not in lines or lid in seen:
            issues.append(f"cinema:{sid}:missing_duplicate_or_unknown_line")
            continue
        seen.add(lid)
        scene_id, scripted = lines[lid]
        speaker = speech.get("speaker_id")
        if (
            scene_id != shot.get("scene_id")
            or speaker != scripted.get("role_id")
            or " ".join(str(speech.get("text", "")).split())
            != " ".join(str(scripted.get("text", "")).split())
        ):
            issues.append(f"cinema:{sid}:dialogue_must_match_screenplay")
        if mode == "native_dialogue":
            dialogue_duration += duration
            if (
                roles.get(speaker, {}).get("kind") != "character"
                or speaker not in shot.get("roles", [])
                or speech.get("voice_id") != roles.get(speaker, {}).get("voice_id")
                or shot.get("visible_speaker_id") != speaker
            ):
                issues.append(f"cinema:{sid}:speaker_or_voice_identity_mismatch")
            if shot.get("audio_pipeline") != "preserve_native_av":
                issues.append(f"cinema:{sid}:native_av_must_be_preserved")
            if not {"native_speech", "lip_sync"}.issubset(
                set(shot.get("capabilities", []))
            ):
                issues.append(f"cinema:{sid}:speech_capable_route_required")
            # The provider records a complete supported-length take. A reviewed
            # native edit can remove a stutter or a lead without stretching the
            # retained performance. Keep generation planning and editorial time
            # separate; never solve a length mismatch by slowing the clip.
            provider_duration = shot.get("provider_take_duration_seconds", duration)
            if (
                not finite_number(provider_duration)
                or provider_duration < duration
                or provider_duration > 60
            ):
                issues.append(f"cinema:{sid}:invalid_provider_take_duration")
                provider_duration = duration
            if provider_duration != duration:
                edit = shot.get("native_editorial_plan") or {}
                if (
                    edit.get("original_av_timing_preserved") is not True
                    or edit.get("retiming") is not False
                    or edit.get("voice_replacement") is not False
                    or not str(edit.get("provenance_sha256", "")).strip()
                ):
                    issues.append(f"cinema:{sid}:native_edit_provenance_required")
            capacity = (
                max(
                    0,
                    min(
                        duration, provider_duration - policy["dialogue_handle_seconds"]
                    ),
                )
                * policy["max_dialogue_words_per_second"]
            )
            if len(str(speech.get("text", "")).split()) > capacity:
                issues.append(f"cinema:{sid}:dialogue_too_long_for_shot")
        elif roles.get(speaker, {}).get("kind") != "narrator":
            issues.append(f"cinema:{sid}:character_dialogue_cannot_be_narration")
    if set(lines) != seen:
        issues.append("cinema:all_screenplay_lines_must_be_delivered_once")
    issues.extend(duration_issues(total, policy, "storyboard"))
    if (
        not total
        or dialogue_duration / total < policy["min_dialogue_duration_fraction"]
    ):
        issues.append("cinema:insufficient_character_dialogue_runtime")
    if (
        not total
        or performance_duration / total < policy["min_performance_duration_fraction"]
    ):
        issues.append("cinema:insufficient_character_performance_runtime")
    return sorted(set(issues))


def pilot_ids(board: dict) -> list[str]:
    selected, speakers = [], set()
    for shot in board.get("shots", []):
        if shot.get("speech_mode") == "native_dialogue":
            speaker = (shot.get("dialogue") or {}).get("speaker_id")
            if speaker not in speakers:
                selected.append(shot["shot_id"])
                speakers.add(speaker)
        if len(selected) == 2:
            break
    return selected


def performance_review_issues(
    review: Any,
    board: dict,
    receipts: list[dict],
    *,
    policy: dict,
    storyboard_sha256: str,
    pilot: bool = False,
) -> list[str]:
    """Validate explicit evidence-bound review, never manufacture attestations."""
    if not policy:
        return []
    if not isinstance(review, dict):
        return ["cinema:performance_review_required"]
    issues = []
    if (
        review.get("status") != "passed"
        or review.get("storyboard_sha256") != storyboard_sha256
        or review.get("policy_sha256") != digest(policy)
        or not str(review.get("reviewer", "")).strip()
    ):
        issues.append("cinema:performance_review_stale_or_unbound")
    if not pilot and not all(
        review.get(k) is True
        for k in (
            "full_scene_playback_pass",
            "acting_review_pass",
            "continuity_review_pass",
            "age_fit_pass",
        )
    ):
        issues.append("cinema:full_film_performance_review_incomplete")
    selected_ids = (
        set(pilot_ids(board))
        if pilot
        else {s["shot_id"] for s in board.get("shots", [])}
    )
    supplied = review.get("shots", [])
    if not isinstance(supplied, list) or any(not isinstance(r, dict) for r in supplied):
        return issues + ["cinema:shot_performance_reviews_required"]
    reviewed = {r.get("shot_id"): r for r in supplied}
    if len(reviewed) != len(supplied) or set(reviewed) != selected_ids:
        issues.append("cinema:exact_shot_review_coverage_required")
    actual = {r["shot_id"]: r for r in receipts}
    for shot in board.get("shots", []):
        sid = shot["shot_id"]
        if sid not in selected_ids:
            continue
        r = reviewed.get(sid, {})
        receipt = actual.get(sid, {})
        if not receipt.get("asset_sha256") or r.get("asset_sha256") != receipt.get(
            "asset_sha256"
        ):
            issues.append(f"cinema:{sid}:performance_media_hash_mismatch")
        if r.get("performance_pass") is not True:
            issues.append(f"cinema:{sid}:acting_not_reviewed")
        if shot.get("speech_mode") == "native_dialogue":
            if not all(
                r.get(k) is True
                for k in (
                    "exact_words_pass",
                    "correct_speaker_pass",
                    "lip_sync_pass",
                    "original_av_timing_preserved",
                    "voice_consistency_pass",
                )
            ):
                issues.append(f"cinema:{sid}:dialogue_or_lip_sync_unverified")
            if r.get("review_method") != "full_utterance_normal_and_half_speed":
                issues.append(f"cinema:{sid}:full_utterance_av_review_required")
            observations = r.get("sync_observations", [])
            if not isinstance(observations, list) or len(observations) < 3:
                issues.append(f"cinema:{sid}:sync_observations_required")
            else:
                times = []
                for o in observations:
                    if (
                        not isinstance(o, dict)
                        or not finite_number(o.get("seconds"))
                        or not 0 <= o["seconds"] <= shot["duration_seconds"]
                        or not str(o.get("visible_and_audible_event", "")).strip()
                    ):
                        issues.append(f"cinema:{sid}:invalid_sync_observation")
                    else:
                        times.append(o["seconds"])
                if len(set(times)) < 3:
                    issues.append(f"cinema:{sid}:distinct_sync_observations_required")
    return sorted(set(issues))
