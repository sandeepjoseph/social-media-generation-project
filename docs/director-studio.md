# Director Studio

Director Studio is a local, resumable workflow layered onto MoneyPrinterTurbo. It starts with one story request, persists phase inputs and hashes in SQLite, and exposes manual review steps for research, production, and publishing. The app does not claim that a research request is a research result or that exported publishing metadata has been posted.

New requests target 420 seconds by default. A read-only legacy import keeps the duration recorded by its source plan; it does not modify that source. The six-episode experiment planner only stages hypotheses and measures. Each episode remains unauthorized for generation and publication until separately approved.

The Streamlit intake asks for one story idea, source URL, or retelling request. A working title is derived from that input; audience, duration, taxonomy, and destinations are optional advanced preferences. Defaults come from an external profile selected by `STORY_STUDIO_PROFILE_PATH` when configured, otherwise from the generic public starter. A URL is stored as a research lead only; it is never presented as fetched evidence.

Run the CLI from the repository root:

```sh
python -m app.services.story_studio --help
python -m app.services.story_studio create examples/story-request.example.json
python -m app.services.story_studio list
python -m app.services.story_studio show STORY_ID
python -m app.services.story_studio research-request STORY_ID --out research-request.json
python -m app.services.story_studio add-evidence STORY_ID evidence.json
python -m app.services.story_studio ingest-screenplay STORY_ID screenplay.json
python -m app.services.story_studio ingest-storyboard STORY_ID storyboard.json
python -m app.services.story_studio storyboard-draft STORY_ID
python -m app.services.story_studio register-variant STORY_ID master.mp4 captions.en.srt --variant-id master-en-v1 --audio-locale en --caption-locale en --fluent-reviewer "Reviewer Name" --voice-json voice-record.json --burn-in-reviewed --burn-in-reviewer "Reviewer Name"
python -m app.services.story_studio export-flow STORY_ID --out flow-bundle.json
python -m app.services.story_studio import-flow-receipt STORY_ID receipt.json
python -m app.services.story_studio qa STORY_ID
python -m app.services.story_studio import-qa STORY_ID reviewer-qa.json --master /path/to/master.mp4
python -m app.services.story_studio resolve-phase STORY_ID creative --verified-no-duplicate-submission
python -m app.services.story_studio experiment-plan "Example series" --out experiment-plan.json
```

The SQLite database and generated exports live under ignored `storage/story_studio/`. `phase_runs` preserves completion/failure records; a completed phase reuses output only when its canonical input hash is unchanged. When its input changes, work is rerun. Evidence, creative documents, provider quotes, media paths, receipts, and analytics imports are separately hashed.

Research remains `needs_research` until a person imports source evidence. The current package ships no paid research/search adapter configuration, so no citation is generated automatically. Screenplay drafting is an explicit UI action through the existing MoneyPrinter provider and cost router; the CLI can import a screenplay JSON. Storyboard drafting is an explicit UI button or `storyboard-draft` CLI action. It requires the current validated screenplay, applies the loaded director profile's role and scene contracts, and validates closed scene/role/reference IDs plus finite positive shot durations before marking the phase complete. Each manual Flow bundle preserves the complete shot-manifest fields, including treatment, camera, lighting, weather, props, audio, and transitions. Provider prices default to unknown; Flow uses a manual browser bundle and a hash-bound receipt. Receipts must match the latest storyboard/prompt export and each shot is counted once; changed story inputs invalidate later phases and revoke approvals. A crashed phase requires explicit recovery, and a possibly submitted provider request is held for human review. `resolve-phase` only releases that hold after the operator confirms no duplicate submission. `provider_account_check_required` is a hold state: do not retry, switch accounts, or attempt to bypass it.

Creative profiles are loaded from `STORY_STUDIO_PROFILE_PATH` when set. The private profile, director template, and asset registry must resolve outside the git checkout. The public fallback contains generic role names and scene contracts only. Loaded asset entries are checked against their SHA-256 before they enter a local Flow bundle. Private profile content is not copied into tracked source files.

The platform package service drafts truthful metadata and current-format checks for YouTube long/Short, Facebook Reels, Instagram Reels, TikTok, Dailymotion, and Rumble. It requires explicit rights coverage for source/adaptation, visual, voice, and music/ambience; an imported reviewer QA report bound to the story, script text, and current master; reviewed audience settings; and a separately verified/reviewed variant for every selected platform. QA also samples actual first/final video frames and an audio segment with the bundled FFmpeg; a filename or asserted check alone cannot pass. Approval must match the exact master and package hashes. Even an approved package remains a manual handoff; publication and analytics account APIs are not configured by this project.

Costs are kept in separate domains: API billing, Flow subscription credits, TTS, and local render time. Unknown costs remain unknown. Voice synthesis is not selected or invoked by storyboard drafting; voice casting, TTS provider setup, and narration QA remain explicit human/provider-specific work, with no silent voice fallback. Analytics imports accept local exports and preserve their source hashes; they do not connect to platform accounts.

Every localized media variant must be registered separately with its media file, voice record, and SRT/VTT caption track. Caption, spoken-audio, voice-record, and story-target BCP-47 locales must match exactly after normalization, the sidecar must contain non-empty valid cues ending within the measured media duration, and a named fluent reviewer must attest to the caption text. The default caption policy also requires a named human check that the sidecar is burned into the video; the application records that attestation but does not infer it from a subtitle file. Registration does not translate text or synthesize speech. The quality gate requires a matching master-language variant; packaging requires an exact-media-hash caption/voice variant for every selected platform. An English caption file cannot approve a Malayalam audio variant. The external profile may configure a delivery destination and timezone; see [`media-delivery.md`](media-delivery.md). Archive receipts record the source and copy hashes, and an enabled delivery policy blocks final QA if a required copy is missing or unverified.

## One-story request

Copy [`../examples/story-request.example.json`](../examples/story-request.example.json) and edit the fields. The contract includes age range/language, fiction taxonomy, learning intent, platform targets, and a target duration. A new project can proceed without research, but quality/package gates stay blocked until the required evidence, rights records, media QA, and per-platform assets are present. `import-qa` accepts a JSON object with `status: "passed"`, matching `story_id`, current `script_sha256` and `master_sha256`, a non-empty `reviewer`, and `technical_decode_pass`, `visual_review_pass`, and `audio_review_pass` set to true. The local decode is independently checked before those attestations are accepted.

The workflow map is `request → research evidence → screenplay → storyboard → manual Flow receipts → assembled master → bound QA → platform-specific package → exact-hash owner approval → local analytics import`. Each completed phase records input/output hashes in SQLite; incomplete or invalidated work remains visible instead of being represented as done.
