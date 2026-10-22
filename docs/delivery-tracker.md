# Portable production and publication tracker

The tracker records media bytes, immutable story editions, and separate platform
observations. It is an offline sidecar: it makes no provider calls, accepts no
terms, changes no approvals and uploads nothing. It can run in a second checkout
while production continues on its frozen implementation. Deploy this code into
the production application only between jobs using the normal drift/replan rules.

New channel setup initializes an empty `delivery-tracker` automatically. Existing
channels use the explicit `init` command below; existing state is never reset.
The channel launcher enables `STORY_STUDIO_DELIVERY_TRACKER_PATH` and rebases its
channel/archive aliases on that laptop. File-backed Studio artifacts and verified
archive copies are then inventoried on registration, with hashes retained in the
artifact's provenance. A missing root binding or write failure holds that import
for reconciliation rather than silently losing its tracker record. Structured
documents stored only in SQLite remain part of the separate database backup.

Keep `catalog.json` and `events.jsonl` in your **private** channel repository.
Never put production records, commercial prompts, credentials or media binaries
in the public source fork. `roots.local.json` maps portable aliases to this
laptop's actual folders and is Git ignored. It is not portable state to commit.

```sh
python -m app.services.studio_delivery_tracker --tracker /path/to/private/channel/tracker init --channel-id my-channel
python -m app.services.studio_delivery_tracker --tracker /path/to/private/channel/tracker bind-root episodes /path/to/episodes
python -m app.services.studio_delivery_tracker --tracker /path/to/private/channel/tracker bind-root archive /path/to/media-archive
python -m app.services.studio_delivery_tracker --tracker /path/to/private/channel/tracker scan episodes --prefix my-story --story-id my-story
```

Scanning calculates SHA256 from actual media, captions, scripts and production
documents (JSON/TXT/Markdown/PDF/CSV/HTML), preserves changed-byte
history and alternate versions, and excludes symlinks and account/proof screenshot
names. It does not delete missing files from history. Verification reports missing
or changed bytes. This is an inventory, not a media backup; transfer the archived
media separately. Review the selected roots before scanning. Never scan browser
profiles, account downloads or secrets folders. The filename exclusions reduce
mistakes but are not a sensitive-data classifier.

Add each complete edition with `add-release /path/to/release.json`:

```json
{
  "release_id": "weaver.en.v2",
  "story_id": "weaver",
  "title": "The Weaver and the Lost Thread",
  "version": "v2",
  "locale": "en",
  "quality": "accepted_ai_review",
  "targets": ["youtube_long", "facebook_reels", "rumble"],
  "master": {"root": "episodes", "relative_path": "weaver/final/movie.en_v2.mp4"},
  "master_sha256": "REPLACE_WITH_THE_ACTUAL_64_CHARACTER_SHA256"
}
```

Use `draft`, `held`, `stopped_private`, or `legacy_not_current_contract` for
unapproved/old work. An accepted AI review is not owner viewing, publication
authority, or guaranteed lip sync. Retain explicit review artifact locators and
hashes in optional `review_evidence` and policy/build hashes in the release.
Add a distinct release ID for different master bytes or locale. Never transfer
acceptance from the title alone. Captions, covers and source takes remain files
in the inventory; platform-specific variants should be separate release IDs if
their bytes differ.

After a real platform action/check, use `record /path/to/observation.json`:

```json
{
  "event_id": "weaver-v2-youtube-2026-10-22-public",
  "release_id": "weaver.en.v2",
  "platform": "youtube_long",
  "status": "public_verified",
  "master_sha256": "REPLACE_WITH_THE_UPLOAD_MASTER_SHA256",
  "observed_at": "2026-10-22T14:00:00+00:00",
  "url": "https://www.youtube.com/watch?v=EXAMPLE",
  "evidence": {
    "kind": "native_library",
    "public_visibility_observed": true,
    "note": "Correct post identity and Public in the official channel library; upload receipt binds the exact file. Playback not checked."
  }
}
```

Statuses distinguish `prepared`, `submitted`, `processing`, `historical_published`,
`owner_reported`, `published_visibility_unverified`, `public_verified`, `private`,
`held`, `failed` and `unknown`.
Only observed official-library/player/API visibility can be `public_verified`;
an owner upload message or an old receipt cannot. Evidence notes should specify
whether actual playback was checked. Use explicit timezone offsets. Events have
idempotency IDs and a SHA256 chain, with serialized atomic writes; duplicate IDs
cannot append changed data. This detects accidental edits, not a malicious actor
who can rewrite the whole ledger. Keep Git history as an additional audit trail.

Before publishing, inspect `report` for an existing URL. Unknown or processing
is a verification task, not permission to upload a duplicate. A previously held
edition must still satisfy Director Studio's current approval contract. The
tracker never authorizes publication or overrides a platform's automation rules.

```sh
python -m app.services.studio_delivery_tracker --tracker /path/to/private/channel/tracker verify
python -m app.services.studio_delivery_tracker --tracker /path/to/private/channel/tracker report --output /path/to/private/channel/tracker/report.json
git -C /path/to/private/channel add tracker/catalog.json tracker/events.jsonl tracker/report.json tracker/.gitignore
git -C /path/to/private/channel commit -m "Reconcile verified production and publication receipts"
git -C /path/to/private/channel push
```

Run scan after saving generated assets, then record each publication observation
immediately after its native result. Registered Studio files are tracked through
the enabled hook; external provider downloads need the explicit reconciliation
scan until imported. Bind any external working folder before importing it. The
publication observations remain explicit operator/CLI steps; there is no
background scheduler or secret-dependent auto publisher.
Never count "upload complete" as public playback, monetization approval or income.

On another laptop, clone the source and private repositories, copy/restore media,
bind the same aliases to the new locations and run `verify` before resuming.
Missing files remain visible as missing until restored. Another channel starts
with `init` and its own empty tracker/accounts; it must not inherit this channel's
publishing authority or social posts. Local writer locking does not coordinate
two laptops: pull/reconcile Git before work, avoid concurrent pushes, and resolve
JSONL conflicts by replaying the real observations through `record`, preserving
event IDs and timestamps rather than manually splicing the hash chain.
