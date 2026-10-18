"""Reuse verified work before paid generation, without reusing creative approval.

Flow charges credits per generated output, not a guaranteed prompt-token rate.
Saved media and deterministic work can be reused; voices, timing and review
requirements cannot be traded away for a cheaper route.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from collections import OrderedDict
from pathlib import Path


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def saved_take(shot, receipts):
    """A saved matching take blocks a duplicate request, even pending review.

    This is idempotency, never an acting/lip-sync verdict. A failed take needs
    explicit review and replanning before another paid request.
    """
    prompt_sha = hashlib.sha256(shot["prompt"].strip().encode()).hexdigest()
    matches = [
        r
        for r in receipts
        if r.get("shot_id") == shot["shot_id"] and r.get("prompt_sha256") == prompt_sha
    ]
    for receipt in reversed(matches):
        path = Path(receipt.get("asset_path") or "")
        if path.is_file() and file_sha(path) == receipt.get("asset_sha256"):
            return {
                "status": "saved_take_available_review_still_required",
                "asset_sha256": receipt["asset_sha256"],
                "receipt_id": receipt.get("receipt_id"),
                "generation_allowed": False,
                "creative_approval_implied": False,
            }
    return {
        "status": "saved_take_changed_or_missing_hold" if matches else "no_saved_take",
        "generation_allowed": not matches,
        "creative_approval_implied": False,
    }


def reusable_asset(specification, records):
    """Exact recipe, rights, media and actual review hashes govern image reuse.

    The specification must include actor/set/style/wardrobe and, for audio,
    words, voice and locale. Similarity alone never matches different recipes.
    """
    fields = {
        "image": {
            "reference_hashes",
            "scene",
            "style",
            "wardrobe",
            "lighting",
            "composition",
            "output_spec",
        },
        "narrator_bridge": {"text", "voice_id", "locale", "settings"},
    }
    kind = specification.get("kind")
    if kind not in fields or any(not specification.get(k) for k in fields[kind]):
        raise ValueError(
            "Reuse requires a complete image or narrator-bridge specification; native character speech stays linked to its video"
        )
    key = hashlib.sha256(
        json.dumps(specification, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    for record in records:
        if record.get("recipe_sha256") != key:
            continue
        path = Path(record.get("path") or "")
        evidence = Path(record.get("review_path") or "")
        if (
            record.get("rights_status")
            not in {"original", "licensed", "public_domain", "cleared"}
            or record.get("review_status") != "passed"
            or not path.is_file()
            or file_sha(path) != record.get("sha256")
            or not evidence.is_file()
            or file_sha(evidence) != record.get("review_sha256")
        ):
            continue
        return {
            "status": "verified_reuse_candidate",
            "recipe_sha256": key,
            "path": str(path.resolve()),
            "sha256": record["sha256"],
            "contextual_review_still_required": True,
        }
    return {"status": "no_verified_exact_match", "recipe_sha256": key}


def cache_friendly_prompt(document):
    """Losslessly remove duplicated template fields and put stable rules first.

    Provider cache hits and billing savings remain measured, never promised.
    Exact dialogue, references, constraints and evidence are not shortened.
    """
    value = copy.deepcopy(document)
    profile = value.get("production_profile") or {}
    template = profile.get("full_director_template")
    if isinstance(template, dict):
        for key in list(template):
            if (
                key in profile
                and key != "full_director_template"
                and template[key] == profile[key]
            ):
                del template[key]
    order = ("production_profile", "output_contract", "task", "constraints")
    ordered = {key: value.pop(key) for key in order if key in value}
    ordered.update(value)
    return json.dumps(ordered, ensure_ascii=False)


class VerifiedDecodeCache:
    """Bounded process-local reuse of real technical decodes of identical bytes.

    Hash before and after decoding. A changed file or decoder never inherits a
    pass; this cache never contains creative or lip-sync review decisions.
    """

    def __init__(self, maximum=256):
        self.maximum = maximum
        self._cache = OrderedDict()
        self._lock = threading.RLock()

    def check(self, path, decoder):
        path = Path(path).expanduser().resolve()
        if not path.is_file():
            return False, "video_file_missing"
        before = file_sha(path)
        key = (before, decoder)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                if file_sha(path) != before:
                    return False, "media_changed_during_cached_decode_verification"
                self._cache.move_to_end(key)
                return cached[0], "reused_actual_decode_of_identical_sha256:" + cached[
                    1
                ]
            result = decoder(path)
            if file_sha(path) != before:
                return False, "media_changed_during_decode"
            if result[0] is True:
                self._cache[key] = result
                while len(self._cache) > self.maximum:
                    self._cache.popitem(last=False)
            return result
