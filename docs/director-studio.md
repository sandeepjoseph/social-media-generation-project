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

## Performed children's films

External profiles can enable the built-in `cinema_policy` with `{"enabled": true}`.
This is an opt-in feature layered onto the existing workflow; generic video jobs
and historical imports retain their contracts. Contract version 2 defaults to a
360–480 second full episode, two speaking characters, no more than 20% narrator
words, at least 55% native-dialogue shot time and 75% character performance time.
These are production defaults, not a scientific claim about an ideal attention
span. A short companion is registered separately and never satisfies full-film
duration. Local profiles can configure the numeric policy for another audience.

The script must identify character/narrator roles, stable original voice IDs,
unique line IDs, scene action, dramatic purpose, estimated duration and a complete
setup/problem/attempt/turn/resolution arc. The storyboard delivers each exact line
once in its scene. Native-dialogue takes name the single visible speaker, assigned
voice, exact words, gaze, emotional turn, blocking, costume and continuity. They
require native speech/lip-sync capabilities and `audio_pipeline: preserve_native_av`.
Dialogue must fit the take with performance handles. Camera-only image movement,
silent people under substituted narration, repeated footage and time-stretching
are forbidden production substitutions; named performance review remains necessary
because structural validation cannot see acting or infer lip sync.

The first Flow export designates two different speaking characters as the pilot.
Only those shots have `generation_allowed: true`; the rest remain held. The
receipt importer rejects bulk receipts until an exact-board/policy/clip-hash pilot
review passes. It also measures cinema clip duration against its shot contract.
After importing the pilot review, re-export the same board to release the rest.
This controls the local workflow; manual provider controls remain an operator
handoff, not an upload/generation API supplied by this application.

Each speaking clip needs a named review of the **whole utterance at normal and
half speed**, exact words, correct speaker, lip sync, preserved A/V timing and
voice consistency, plus at least three distinct timed audible/visible articulation
observations. Correct transcription or still frames alone cannot pass. The final
QA report's `performance_review` binds the current storyboard and resolved policy
hash, covers every receipt asset hash, and records full-film acting, continuity,
age fit and scene-playback review. The outer report still binds the script and
final-master hashes. Measured final duration is independently gated; decoding and
caption checks alone cannot approve a film. Human attestations are recorded as
attestations; the software does not claim an automatic phoneme-perfect detector.

## Current templates and production learning

New projects read the external profile, director template, verified references and
applied learning rules anew, then freeze those hashes and the implementation
content identity/Git revision. No template is silently swapped under an active
production. The UI shows drift; cinema generation, packaging and approval stop
until **Apply latest template and replan** is explicitly chosen. Replanning keeps
evidence/source media and the artifact history, resets creative and later phases,
updates an out-of-range full-episode target and revokes prior approvals. It refuses
to change a project with a running phase.

The profile may set `private_learning_log` to an external JSON file with
`revision` and `entries`. Entries with `status: applied` become new-project rules;
`experiment` entries do not. The UI saves either, and each change advances the
revision. This provides a reusable improvement history, not an unattended claim
that quality increases every day. These private rules never enter tracked code.
The existing upstream monitor opens review PRs; it never replaces this custom
build with an unreviewed upstream package during production.

```sh
python -m app.services.story_studio profile-status STORY_ID
python -m app.services.story_studio refresh-profile STORY_ID
python -m app.services.story_studio import-performance-pilot STORY_ID pilot-review.json
python -m app.services.story_studio record-learning --criterion acting --text "Keep listening reactions motivated" --status applied
```

## Reviewed native movie assembly

The Quality tab assembles an explicit reviewed selection of moving clips.
The selection binds the current storyboard, provider recipes, immutable component
decisions, source hashes and original frame intervals. Every scene appears once
in story order. Missing or repeated footage, changed dialogue, unreviewed acting,
time stretching and substituted narration are held. Editorial duration may differ
from provider take length only with explicit preserved-A/V edit provenance.

Build a **review cut** first with original actor audio and matching SRT, VTT and
burned captions. Final mixing needs a named whole-playback review bound to the
exact ordered media plan and review-cut hash, plus music rights evidence bound
to the actual score. Audio and captions must share the story locale. Non-English
captions need reviewed line breaks and a verified font; English is no fallback.

Native 24fps shots and 48kHz stereo PCM are concatenated in one pass before the
final AAC export, avoiding joined per-shot AAC encoder padding. Full-frame decode
and timestamp checks do not establish acting, lip sync or editorial quality.
Exports retain `publication_allowed: false` pending final Quality review and never
overwrite an existing output. The UI registers generated videos and captions
through the configured private media-delivery policy, preserving dated,
story-named copies and source hashes.

```sh
python -m app.services.studio_native_movie storyboard.json selection.json \
  --output review-cut.mp4 --review-cut
python -m app.services.studio_native_movie storyboard.json selection-with-review.json \
  --output final-candidate.mp4 --music score.wav --music-rights score-rights.json
```

CLI rendering is local and never publishes or alters accounts. Register CLI
outputs in the Studio or reconcile them through the media archive before delivery.
Commercial prompts and selections remain local.
