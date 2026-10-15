# Media delivery archive

`app.services.media_delivery` provides opt-in, artifact-by-artifact archival for generated or imported stills, video, audio, and captions. It never walks the repository or moves working files. The destination is supplied by runtime policy and must be configured outside the source checkout. The public default has no destination and returns `status: "unconfigured"` with `copy_verified: false`.

```python
from app.services.media_delivery import (
    MediaArchivePolicy,
    MediaArtifact,
    add_artifact,
)

policy = MediaArchivePolicy.from_mapping(settings.get("media_delivery"))
receipt = add_artifact(
    MediaArtifact(
        source_path=generated_media_path,
        story_title=story_title,
        kind="generated_video",
        provenance="generated",
        locale="en",
        variant_id="v2-final",
        created_at=job_created_at,
    ),
    policy,
)
```

Supported artifact kinds are `generated_image`, `imported_image`, `reference_image`, `generated_video`, `imported_video`, `generated_audio`, `imported_audio`, `generated_caption`, and `imported_caption`. Each kind must match its extension allowlist. Provenance is restricted to `generated`, `flow_receipt`, `reference_import`, and `manual_import`. A Flow receipt importer should archive only eligible media/caption files; receipt JSON, payment evidence, account/login screenshots, and configuration files are not archive artifacts.

The policy mapping accepts only `enabled`, `destination`, `timezone`, `archive_on_generation`, and `preserve_versions`. Set timezone according to the user's profile. With generation archival disabled, generated items return `status: "disabled"`; imported items remain eligible when the archive is enabled. The default `MediaArchivePolicy()` has no destination and never writes.

An archived item is placed under a `YYYY-MM-DD_story-title` folder. Its filename repeats the date and readable story slug and includes artifact kind, optional locale suffix (for example `.en` or `.ml`), optional variant ID, and a content-hash suffix. Unicode letters and combining marks are retained in readable slugs, and path separators are removed. Content changes create a different path. Repeating the same source/version is idempotent.

Copies use a temporary file in the destination folder, stream SHA-256 while copying, compare the copied hash and source metadata, atomically replace the final filename, then verify the published file. The source is never deleted. A locked, atomically replaced `media-delivery-manifest.json` records absolute source and archive paths, hash, byte count, date basis/timezone, kind, provenance, locale, variant ID, and verification status. A mismatching existing file or unreadable manifest raises `MediaArchiveError`; the service does not silently overwrite it.

Callers should persist the returned receipt on the job/artifact record. An `unconfigured`, `disabled`, or rejected result is not an archive receipt and must not be presented as verified delivery.
