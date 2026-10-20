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
and historical imports retain their contracts. Contract version 3 defaults to a
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

## Provider composer preflight

Before one reserved provider activation, observe the entire actual composer text,
selected reference asset hashes, visible role, saved voice, native audio, duration,
output count, model and live credit quote. Read the composer after replacement:
some contenteditable controls retain old text. A substring match is insufficient.
Reusing ingredients does not imply the next shot has the same actor or props.

Create an observation JSON with `shot_id`, `prompt_text`, `reference_sha256`
(a list), `visible_speaker_id`, `voice_id` (null for non-speaking action),
`native_audio: true`, `output_count: 1`, `duration_seconds`, `model`,
`quoted_credits`, and `observed_by`. These must be actual observations, not values
blindly copied from the desired recipe. Then run:

```sh
python -m app.services.studio_provider_preflight bundle.json SHOT_ID observation.json --out attestation.json
```

Keep the credit reservation separate, activate Generate once, and attach the
resulting document as `submission_attestation` in the downloaded take's receipt.
Fresh cinema sources are rejected without a current, unchanged attestation.
Already imported exact source hashes need no fabricated historical observation.
A local derivative may identify an imported original with
`native_original_source_sha256`; this inherits submission provenance, never a
performance pass. Word accuracy and preflight do not establish lip synchronization.
Every original or edited source still needs the required actual A/V review.

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

Long native utterances may supply `caption_cues` with local `start`, `end`,
`text` and optional reviewed `lines`. These cues use the selected actor's word
timing, preserve the complete script exactly once, and cannot overlap or exceed
the clip. English cues use at most two 42-character lines. Localized cues require
explicit reviewed line breaks. Caption validation runs before rendering; it does
not shorten, replace or stretch the actor's performance.

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

Before rendering English, prepare a separate readability candidate:

```sh
python -m app.services.studio_native_movie storyboard.json selection.json \
  --prepare-readable-captions --output readable-selection.json
```

This combines short trailing cards when the complete line fits two 42-character
lines and extends cards into existing pauses toward two seconds and 16 characters
per second. It never changes words, source clips, voice timing or shot duration.
Insufficient existing time is recorded as a hold for explicit editorial replanning.
The new candidate revokes sequence approval and still needs actual caption and
whole-movie review. Other languages require fluent-reviewed line breaks and timing.

## Mandatory cinema finishing (contract 3)

Once a profile enables cinema, the finishing contract is mandatory. A channel
can additionally set `mandatory_cinema: true`; its profile then fails to load if
cinema is disabled. Mandatory channel profiles also require a matching director-template revision, applied-learning revision and `required_cinema_contract_version: "3.1.0"`; missing or mismatched files fail closed. Generic upstream jobs remain unaffected. Production build
identity includes caption, finishing and growth implementations, so changes
hold frozen cinema jobs for explicit replan and revoke downstream approvals
through the existing refresh operation. Historical uploads are never repaired
or reapproved by changing a template.

Before generation, the board must specify the story clock, weather, lighting,
camera, eyeline, physical action, costume, before/after prop states, sound cues
and transition. Speaking performers retain their native voices and original A/V
timing. Each component review must explicitly check unintended speech; speaking
shots must also have a complete sentence and clean rest. The two-speaker pilot,
full-utterance normal/half-speed reviews and full-film duration gates still apply.

Caption readability is checked by default before native rendering and again
against the actual localized sidecar during final QA. English cards require at
least two seconds, no more than 16 characters/second, two lines and 42 characters
per line. Ordered text must reproduce the storyboard dialogue exactly once.
Overlaps, final-word flashes, missing words and stale locale bindings hold the
release. `--prepare-readable-captions` can propose extensions into existing pauses
or merge a short sentence; it never changes actor timing. Crowded cards require
explicit editorial replanning, never slower speech or invented word timings.
Other languages require their own fluent typography and timing review; English
character limits are not represented as a Malayalam fluency test.

The QA JSON must now contain `finishing_review`. In Director Studio's Quality
tab, **Prepare unpassed finishing checklist** downloads a source-bound pending
checklist; the same API is `story_studio.finishing_review_template(store,
story_id, master_path)`. A generated checklist is not a passing review. Fill it
only after actual review, preserving the raw report in a hash-bound local file.

The finishing review binds story ID, final master, current captions, storyboard,
resolved cinema policy and locale. It requires:

- Actual complete-movie audio/video review, a named reviewer, explicit
  `reviewer_kind` (`human`, `ai`, `assisted`), media-access confirmation and honest
  limitations. A sampled AI review must describe its sampling; no human viewing
  or phoneme-perfect claim may be invented.
- All named creative checks: plot fidelity and complete ending; acting,
  listening and dialogue; likeness/proportions/cast count; wardrobe, sets,
  props, camera/eyeline/action; chronology/weather/light; native voice/timing;
  pleasant age-appropriate music, intelligibility and clean boundaries;
  matching readable captions; no padded footage; independent story delivery.
- Every shot's opening, ending and join checked on the actual final timeline,
  with a specific observed detail and no unintended voices, clicks or cut-off
  words. This includes action-only shots. Checks must cover the exact board in
  order, including the beginning and ending.
- At least three distinct, bounded `start_seconds`/`end_seconds` audiovisual
  observations spanning the beginning, middle and ending; preserved review files must exist and match SHA-256. Ambiguous
  MMSS-as-seconds values or out-of-range observations are rejected. Resolve
  contradictory reports against actual excerpts and preserve negative evidence.
- An empty `unresolved_issues` list. A component pass, transcript, technical
  decode or an exported file cannot substitute for final creative acceptance.

Final QA, QA import and exact-package owner approval independently recheck these
requirements. The software validates evidence and objective constraints; it does
not automatically judge subjective performance or hear defects. Failed or
changed candidates stay held. No extra provider credits are spent by these checks.

`build_platform_package(..., metadata={...})` accepts prepared `platform_titles`,
`platform_descriptions`, `topics`, `keywords` and `chapters`, also available in the
Packaging UI. Request defaults are retained unless explicitly overridden. Cinema
packages require prepared text for every selected platform plus relevant tags
and keywords. Metadata becomes part of the exact approved package hash; it cannot
supply fake QA, rights or audience approvals. Keep narrow relevant tags (up to
five), truthful hooks and thumbnails, native child-directed/AI controls, matching
captions, primary-account-only distribution and verified dated archives. No
metadata strategy guarantees views or monetization. Platform authorization and
manual handoff restrictions remain in effect.

Each story retains its own movie, captions, metadata, reviews, publication
receipts and dated media archive. New policy revisions do not combine films,
replace old public uploads or silently reuse their approvals.


## Reuse before generation

Flow exports now disable another request when a matching shot/prompt receipt
identifies an unchanged saved take. This includes pending review: saved work
needs evaluation or explicit replanning, not another automatic paid request.
A missing/changed previously saved take is held for recovery. Every request
specifies one output; a request producing several outputs can consume credits
for each. Existing acting, lip-sync, duration and final-film gates still apply.

`studio_efficiency.reusable_asset` verifies exact recipe, rights, asset and review
hashes for approved stills and narrator bridges. Scene/character/style/costume,
lighting/composition/output settings, or exact words/voice/locale must match.
Native character speech is never a separately cached TTS substitute. New scene
context still requires review, even when the asset is reusable.

LLM prompts retain every rule, exact dialogue and evidence while removing
duplicated template fields and placing stable production rules first. The
provider decides cache eligibility; report actual usage rather than promising
a discount. A bounded local technical-decode cache reuses only a real passing
decode of identical SHA-256 bytes under the same decoder. It rehashes before
and after checking; it never caches creative or synchronization approval.

The external profile may require `production_attribution` with `credit_line`,
`required_hashtags` (at most four, reserving one of five for the story), and
`search_keywords`. These owner-supplied producer facts are separate from story
topics. Every platform description receives the exact credit and canonical tags,
including supplied description overrides; company names enter search keywords.
Credits and tags are included in the exact approval hash. No company names or
commercial relationships are hardcoded in the public application.

Cost research, checked 2026-10-18:

- [Flow credits](https://support.google.com/flow/answer/16526234?hl=en): costs are per output, depend on model/plan, and must be rechecked in the current prompt settings. Shortening a prompt alone does not establish credit savings.
- [Flow capabilities](https://support.google.com/flow/answer/16352836?hl=en): image ingredients and available features differ by model; included no-charge image options may be candidates after actual quality review.
- [Google video best practices](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/best-practice): use a high-quality staged source, focus image-to-video instructions on the motion, and keep one focused event per short take.
- [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching): stable prefixes enable eligible cache reuse; billing and cache eligibility depend on the model.
- [OpenAI image generation](https://developers.openai.com/api/docs/guides/image-generation): track actual usage/settings; eligible image-input cache pricing is API-route-specific.
- [YouTube monetization policies](https://support.google.com/youtube/answer/1311392?hl=en): asset reuse must still create distinct, original, useful storytelling. Repeated footage, mass-produced near-duplicates and padding are not cost optimizations.

Use current, account-confirmed quotes and an accepted two-character native pilot
before switching to a cheaper speech model. Draft-resolution generation and
upscaling remain experiments until their final performance/visual quality passes.
Prefer local caption/audio repairs with documented source/packet identities,
approved set/actor references, cached unchanged planning, and regeneration of
only the failed shot. Keep subscription allowances, Flow credits and API money
as separate ledgers; never treat missing prices or unmeasured savings as zero.

### Local finishing from a saved native timeline

The Quality assembly form and `app.services.studio_native_finish` can reuse an
existing, hash-bound native picture/PCM timeline for corrected captions and a
fresh sound mix. Source and current plans must retain identical ordered actor
clips, original frame intervals, words, voices, durations and locale. The source
receipt must bind its original plan and complete technical decode. Corrected
caption candidates pass the same readability checks before rendering.

Audio cleanup requires a reason and unchanged actual review-evidence file hash
for every altered shot. Sample-based trims/padding retain the original clock;
action-only slots carry no unintended generated dialogue. Original speech is
never resynthesized. Music and license evidence are independently hashed.
After loudness normalization, the mix is explicitly resampled to 48 kHz and
conformed to the original timeline's exact sample count before AAC encoding.
The decoded final audio must still fit the existing codec tolerance; a matching
container duration cannot substitute for this check. This conformance preserves
the native performance clock and never authorizes shortened dialogue or video
padding. The receipt records expected and decoded samples and the sample rate.
This is a local render with zero new provider generations, not a quality pass.
The entire final video and audio are decoded; final audiovisual/creative review
and current profile/version gates still determine release. Every output uses a
new filename, and the Studio archives generated outputs and caption sidecars.

### Submission and review evidence before more spending

Every Flow bundle includes mandatory submission and review-capture acceptance
instructions. Reserve credits before one Generate click. If its acknowledgement
is uncertain, keep that attempt reserved and inspect saved provider jobs before
any retry. A retained composer or a virtualized gallery without the new card is
not proof that no job was submitted. Preserve failed/alternate takes and reconcile
the ledger. The existing uncertain-phase hold requires explicit resolution;
Studio cannot observe clicks made outside its manual handoff.

For browser-assisted reviews, retrieve the complete rendered response (for
example, a code element's `textContent`) before treating a short accessibility
snapshot as a truncated model response. Parse the JSON and check exact ordered
coverage against the storyboard. Never rerun a review merely because the UI
only exposes part of an otherwise complete response, and never approve missing
rows. Native component observations must contain at least three distinct finite
numeric timestamps, within the selected take, and actual visible/audible events.
Assembly now checks this before rendering as well as at final QA. Legacy numeric
strings/ranges require explicit curation retaining the original evidence and
timing representation; the gate does not silently invent precision or viewing.

### Continuous native speaking takes

A native-dialogue single must use one continuous interval from one original A/V
source, with the selected duration matching that source's native frame clock.
Do not splice a restarted word or cover a broken utterance with a silent actor
and call it an accepted single. Preserve the failed source, record the defect and
request a new fluent native take within the current authorized credit budget.
Action/reaction shots can remain separately planned non-speaking slots; they
cannot conceal a failed speaking performance. Normal/half-speed, boundary and
whole-film reviews are still required for the replacement.
