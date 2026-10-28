# Director Studio — customized MoneyPrinterTurbo

A local, resumable production application for performed animated stories. This
fork adds researched screenplays, acting and native-dialogue contracts, current
private production rules, reusable assets, locale-bound captions, movie acceptance
gates, platform metadata and portable channel setup to
[MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo).

**Use this README for the customized workflow.** The inherited short-video/TTS
workflow is documented separately in [upstream English](README-en.md),
[upstream Chinese](README-upstream-zh.md) and [upstream Japanese](README-ja.md).
An upstream feature or provider listing is not proof that it is configured,
authorized, tested for acting, or connected to a publishing account in this fork.

| Start here | Details |
| --- | --- |
| [Production architecture and customization report](docs/production-architecture.md) | Products, responsibilities, data contracts, session boundaries and implementation map |
| [Director Studio operator guide](docs/director-studio.md) | Phase actions, evidence, native performance and finishing |
| [New laptop / separate channel](docs/new-channel-setup.md) | Isolated settings, fresh accounts and reusable private policy |
| [YouTube discovery and engagement](docs/youtube-discovery.md) | Search readiness, evidence, comments and notification restrictions |
| [Media delivery](docs/media-delivery.md) | Dated copies, version preservation and hash verification |
| [Portable file and publication tracker](docs/delivery-tracker.md) | Private media inventory, immutable editions, verified platform receipts and laptop handoff |
| [Browser resource policy](docs/browser-sessions.md) | One working tab per needed service, safe cleanup and interrupted-connection recovery |

## What is implemented

The custom application is **Director Studio**, served at
`http://127.0.0.1:8511/Director_Studio` when launched on port 8511. It stores
production state locally and makes explicit, configured LLM calls for screenplay
and storyboard drafts. Research import, image generation, Google Flow generation,
actual audiovisual review and platform publication include operator handoffs.
Exporting prompts, a finished render or a metadata package does not perform or
prove those external actions.

New channels initialized with the supplied CLI receive an enabled movie contract,
search-readiness policy and permitted-engagement preferences. The bare generic
profile is a minimal fallback; restore a reviewed private profile to reuse your
commercial direction, brand and applied learning. The actual private-channel
inventory and operating locations belong in that private repository's README.

Each new channel also receives an empty portable delivery tracker. Its launcher
enables file-backed artifact and archive-copy inventory on registration; external
downloads can be reconciled with the scan CLI. Private version/locale records and
separate per-platform observations preserve what was generated, accepted, held,
submitted, processing or actually verified Public. Local root mappings stay off
Git so another laptop can restore media, bind its paths and verify hashes before
resuming. This ledger does not approve a film or perform publishing. See the
[tracker guide](docs/delivery-tracker.md).

Native finishing preserves the exact 48 kHz timeline after loudness normalization
and checks decoded audio samples. Source-review timestamps are validated before
rendering as well as at final acceptance. Every Flow handoff also carries the
mandatory one-click/reserved-attempt and complete-review-response contracts;
external browser actions still require operator reconciliation and verified
publication receipts. See the [operator guide](docs/director-studio.md).

Final scoring can reuse the exact native concat from a prior canonical review
cut with `--native-render-cache /absolute/path/to/review-cut.json`. Reuse checks
the ordered media-plan digest, storyboard, duration, original-voice/timing flags,
source bytes and every decoded native frame before copying it. A changed shot,
caption plan or review binding rejects the cache. Component, whole-sequence,
rights, final-film and owner-publication gates still apply; a cache is only a
technical optimization, and never a creative approval.

For a new movie, `app.services.studio_native_movie --prepare-native-sequence`
can prepare a reviewed-component PCM `.mkv`, its receipt and localized captions
without a redundant unscored HD encode. Feed that exact receipt and source plan
to `app.services.studio_native_finish`, then perform complete scored-film and
every-boundary audiovisual review before any approval. The finisher preserves
selected native room tone by default and conforms the final audio to 48 kHz;
an explicit non-speaking mute requires source-review evidence and cannot mute
actor dialogue. None of these preparation steps permits publication.

## Products used and their responsibilities

The following components have distinct responsibilities. External assistant/browser
work performed during project development is not an unattended runtime service.
The private deployment report distinguishes historical trials from current use.

| Product/component | Responsibility | Required input and expected output | Boundary |
| --- | --- | --- | --- |
| MoneyPrinterTurbo upstream | Shared application framework, settings, provider integrations and media utilities | Local configuration and installed dependencies → reusable application services | Its stock-footage/TTS path cannot substitute for accepted character performance |
| Customized Director Studio / Streamlit | Story intake, workflow, review forms, packaging and channel onboarding | Story request plus private policy → persisted projects and reviewable artifacts | UI actions do not imply provider or publication approval |
| ChatGPT / Codex assistant | Assisted research, production planning, reference-image work, implementation and operator coordination | Owner brief and authorized tools → drafts, code changes and evidence-backed handoffs | Conversation state is not the production database; copying this repository does not install an assistant session or browser login |
| Anthropic Claude API | Configurable screenplay/storyboard text provider used in the project | API credentials, model/endpoint and workspace selection when needed → structured draft text | Drafts must pass local schema/story checks and actual production review |
| OpenAI image tools / image API integration | Character references, staged stills and covers through the route actually selected | Image brief, approved references, settings and appropriate account/API access → saved images | Included assistant usage and direct API billing are separate; stills do not prove animation or likeness consistency in motion |
| Google Flow / Veo | External moving-character and native speaking A/V generation | Exact staged references, one-shot prompt, supported capability and current credit quote → downloaded take | Manual/browser handoff; no general Flow generation adapter is supplied by Director Studio |
| Google AI Studio / Gemini | Independent assisted review of fictional clip/final-film A/V | Authorized exact media and review criteria → saved review observations with declared limitations | AI review is not human viewing or automatic lip-sync certification |
| Kokoro / narration tools | Historical narration experiments and optional brief narrator bridges | Exact text, voice, locale, settings and rights → audio asset | Cannot replace native character dialogue or alter its timing |
| FFmpeg, PyAV, MoviePy and audio utilities | Local assembly, readable captions, mix and technical verification | Reviewed clip selection, source timing, captions and rights-cleared sound → versioned review cut/master and receipts | Decoding/export success is separate from creative acceptance |
| SQLite and local filesystem | Durable project state, hashes, artifacts, reviews and analytics imports | Validated phase inputs → resumable audit history | Keep channel storage separate; do not commit credentials or media |
| Git / GitHub / Actions | Public reusable source, private policy backup, tests and upstream review PRs | Reviewed changes → commits, checks and proposed updates | Upstream monitoring does not approve or merge updates or replace an active production |
| YouTube, Facebook, Instagram, TikTok, Dailymotion, Rumble | Distribution destinations and platform analytics sources | Accepted exact variant, localized captions, approved metadata and native controls → verified post/receipt | Prepared packages are manual handoffs; accounts, permissions, monetization and payout setup are separate |

Model names, availability, features and prices must be checked for the actual
account before use. Record the chosen model, settings, quote and observed cost
with the job instead of documenting a guessed permanent "best" model. See
[official OpenAI usage/billing guidance](https://learn.chatgpt.com/docs/pricing),
[Claude authentication](https://platform.claude.com/docs/en/api/overview) and
[Flow model capabilities](https://support.google.com/flow/answer/16352836?hl=en).

## Customized session architecture

```mermaid
flowchart LR
    Owner["Owner: story, preferences, budget and authority"] --> UI["Director Studio UI / CLI"]
    Policy["Private channel profile + director template + applied learning"] --> Snapshot["Frozen episode policy and implementation hashes"]
    UI --> Snapshot
    Snapshot --> DB["SQLite story_id, phases, artifacts and approvals"]
    DB --> Draft["Explicit configured LLM draft calls"]
    DB --> Handoff["Research / image / Flow / review handoffs"]
    Handoff --> Media["Downloaded original takes and review evidence"]
    Draft --> Gates["Screenplay, storyboard, pilot and performance gates"]
    Media --> Gates
    Gates --> Finish["Local native-A/V assembly, captions and sound"]
    Finish --> Review["Actual final-film review + duration + rights + archive gates"]
    Review --> Package["Locale/platform variants + search + credits + exact package hash"]
    Package --> Approve["Exact master/package approval"]
    Approve --> Platforms["Authorized native platform handoff"]
    Platforms --> Receipts["Observed publication and analytics records"]
    Media --> Archive["Verified dated media archive"]
    Finish --> Archive
```

| Session boundary | State and responsibility | Resume / change behavior |
| --- | --- | --- |
| Assistant/operator session | Plans and coordinates external actions; imports actual evidence | Resume from the saved story ID/artifacts, not recollection or a chat promise |
| Channel session | External `config.toml`, profile/template/learning, account inventory, cost settings, storage and archive root | Each channel has its own private directory; another port alone does not isolate credentials/data |
| Episode session | Immutable initial policy/build snapshot, screenplay, storyboard, source/clip/QA hashes and phase history | Same inputs may reuse completed work; profile/implementation drift needs explicit replan and revoked downstream approvals |
| Provider job / browser session | Real account capability, quote, authorization, request/prompt and output receipts | A saved take prevents duplicate submission; uncertain submission or account/security checks require recovery before retry |
| Release session | Exact localized media/captions, rights/audience/AI decisions, metadata and owner approval | Any relevant byte/text change invalidates exact approval; live posts require their own observations |

The SQLite schema records `stories`, `story_phases`, `phase_runs`,
`source_evidence`, `artifacts`, `flow_receipts`, `approvals` and
`analytics_imports`. No chat message, cached decode, screenshot or generated
checklist by itself becomes an accepted release. This is a single local workflow
with production-role briefs; it does not launch an autonomous crew of agents.

## Customizations and mandatory production expectations

| Customization | Expected behavior |
| --- | --- |
| Performed movie contract | New full children's episodes default to ages 6–10, 360–480 seconds, usually 420; a Short is a separate companion |
| Production-role briefs | Researcher, writer, director, choreographer, cinematography/camera, lighting/art/costume, sound, captions, growth and reviewer each supply their planned decisions |
| Native actor A/V | Characters visibly act, listen and speak their own exact lines in stable voices; no closed-mouth narrator substitution |
| Pilot and shot review | Two different speaking characters pass the exact native-A/V pilot before remaining generation; each whole utterance receives actual normal/half-speed review |
| Reviewed generation batches | After the pilot, release at most four new shots, then hold until complete source-bound native A/V review passes; unresolved findings override positive booleans. See [batch gates](docs/generation-batches.md) |
| Review integrity | The exact source review must identify one unambiguous shot and report its complete heard words; missing transcripts, another shot's line, omitted words or repeated speech hold native assembly even when a curator marked it passed. Word agreement is only a negative consistency check and never proves lip sync or acting quality. |
| Continuity and final acceptance | Plot, actors, proportions, costume, props, eyelines, motion, time/weather/light, clean boundaries, pleasant sound and complete ending are independently reviewed |
| Locale captions | Media, audio, voice record and SRT/VTT locales agree; English readability is checked, and each localization requires fluent review |
| Maximum reuse | Reuse verified actor/set references and saved native takes; stable prompt prefixes and local caches retain exact constraints and original acting/timing |
| Provider composer preflight | Read back the complete actual prompt, actor, exact reference hashes, saved voice, native audio, duration, one-output setting and current credit quote before activation; a new cinema receipt requires the matching attestation |
| Local finishing | Caption/sound repairs reuse a verified native timeline; no silent TTS replacement, stretched speech, repeated-shot padding or new generation when a local repair suffices |
| Evidence and versioning | Latest private rules/build are snapshotted; drift holds production for explicit replan; negative reviews and originals remain historical |
| Growth package | Accurate platform-specific titles, descriptions, relevant tags, category suggestions, localized captions, company/copyright credits and required AI/audience controls |
| Search and engagement | Main story subject in YouTube title/opening description, supported aliases, episode context and metadata limits; observed visibility is separate from rank; comments/alerts requested only where permitted |
| Archive and publication | Verified dated media copies and exact approved package are required; no claim of upload, availability or monetization without evidence |

The composer preflight rejects appended old script text and ingredients left over
from another character. It records an operator's UI observations; it does not
inspect provider internals, guarantee billing limits or approve acting. Existing
verified source files remain reusable without inventing historical preflight
records. Derived media can cite a known original, while all native timing,
performance and final-film gates still apply. See the
[operator procedure](docs/director-studio.md#provider-composer-preflight).

YouTube Made for Kids videos cannot enable comments or notifications. Other
platforms require checking actual eligible controls, retaining moderation and
viewer preferences. Metadata cannot force indexing, virality or revenue. See
[YouTube audience restrictions](https://support.google.com/youtube/answer/9527654?hl=en)
and [search guidance](https://support.google.com/youtube/answer/58097?hl=en).

## Install and create a separate channel

Use Python 3.11+ and a working FFmpeg runtime. Install dependencies from this
reviewed checkout; `uv.lock` is the pinned environment. The legacy pip route is
available in `requirements.txt`. See the upstream guide for OS-specific setup.

```sh
git clone --branch codex/native-batch-quality-gate https://github.com/sandeepjoseph/social-media-generation-project.git
cd social-media-generation-project
uv sync --frozen --group dev
```

Keep private state outside the checkout. With your authorized private backup
already extracted or cloned, initialize once and launch:

```sh
uv run --frozen python -m app.services.studio_channel_setup init \
  --root "$HOME/StoryStudioChannels/my-channel" \
  --channel-id my-channel --channel-name "My Channel" \
  --source-profile "/path/to/private-policy/brand-profile.json" \
  --rights-owner "Your Company Inc."
uv run --frozen python -m app.services.studio_channel_setup launch \
  --root "$HOME/StoryStudioChannels/my-channel" --port 8511
```

Use the actual backup filename. Omitting `--source-profile` produces generic
rules, not your commercial template. Configure this channel's own provider keys,
model access, billing controls, account logins, ownership and publication authority.
`accounts.json` is an inventory, not an OAuth connector. New setup copies no
credentials, media, old approvals or account connections. Review inherited subject
aliases, company attribution and categories before using a different channel.

The initializer creates private profile/template/learning files, an empty asset
registry, `config.toml`, cost overrides, `accounts.json`, `channel.json` and storage.
The launcher sets `STORY_STUDIO_PROFILE_PATH`, `STORY_STUDIO_CONFIG_PATH`,
`STORY_STUDIO_STORAGE_ROOT` and `STORY_STUDIO_COST_OVERRIDES_PATH`. Media defaults
to `~/Desktop/Deployments/Social/<channel-id>` with date/story/version filenames.
To run another channel concurrently, use another root and port, such as 8512.
A source ZIP is a code snapshot without Git update history.

## Minimum input and normal use

In Director Studio, provide a story idea, source URL or your retelling. Advanced
preferences can override language, audience, duration and platforms. A source URL
is a research lead until actual evidence has been retrieved and imported.

For CLI intake, use [the request example](examples/story-request.example.json).
The minimum JSON API/CLI contract needs both a working title and premise:

```json
{
  "title": "The Weaver and the Lost Thread",
  "premise": "Create an original story about a weaver who learns to ask for help.",
  "audience": {"language": "en"},
  "target_duration_seconds": 420
}
```

For an initialized isolated channel, launch its UI as above. If using the lower-level
CLI, supply that channel's launcher-equivalent environment and the intended DB;
a bare CLI command otherwise uses default local storage/profile settings.

| Step | Supply / do | Required result |
| --- | --- | --- |
| 1. Intake and research | Story input, source leads, actual references and rights evidence | Saved story ID, current policy/build snapshot and verified plot claims |
| 2. Screenplay | Roles/voices, exact line IDs, motivations, arc and timing | Source-supported, age-appropriate structured screenplay |
| 3. Storyboard | Every exact line once; camera, blocking, costumes, props, light, weather, transitions and sound | Valid shot manifest and continuity/performance contract |
| 4. Reference and pilot | Approved set-specific cast references, account quote and bounded budget | Two distinct actual speaking takes with passing bound pilot review |
| 5. Generation and review | Only allowed shots; download originals and import matching receipts | Per-shot source hashes, entire-utterance/acting reviews and bounded retries |
| 6. Assembly and finishing | Reviewed ordered moving clips, locale captions and rights-cleared pleasant sound | Native-A/V review cut, sequence review and versioned finished candidate |
| 7. Quality | Actual full-film A/V and every boundary, measured duration, rights and archive verification | Passing current evidence-bound acceptance; failures remain held |
| 8. Packaging and release | Localized platform variants, prepared metadata, audience/AI decisions and exact approval | Authorized native handoff plus actual saved publication observations |
| 9. Learning | Real analytics and specific feedback | Applied private rules or clearly labelled experiments for future jobs |

Production phases are `research → creative → screenplay → storyboard → flow →
assembly → quality → packaging → approval → analytics`. Consult the
[operator guide](docs/director-studio.md) for import schemas, actual commands and
recovery actions. Exporting a Flow bundle does not call Google; creating a
publication package does not post it.

## Limits, maintenance and validation

API money, included assistant usage, Flow credits, TTS usage and local compute are
separate cost domains. Unknown prices remain unknown; a local budget preference
is not a provider hard spending cap. Shorter Flow prompts alone do not establish
credit savings. Stop on account/security warnings or uncertain charge status;
recover rather than repeatedly submit. Optional providers from upstream need
separate evaluation and a quality pilot before entering this movie path.

Publication/analytics account adapters are not configured by Director Studio.
A supported authorized API can be integrated deliberately; browser-assisted work
still needs platform permission and a working signed-in connection. Rumble remains
an owner-operated manual handoff without the required platform permission. Bank,
tax and monetization eligibility processes belong to the owner and each platform.
Old uploads are not repaired by template or metadata changes.

Update by reviewing upstream PRs and test results, preserving custom behavior and
private policy. The included upstream-monitor workflow prepares review PRs against
fork `main`; it never auto-approves or merges. Until the custom branch is merged,
keep using the documented production branch and review incoming changes there.
Do not pull an unrelated vanilla checkout over an active production.

Run the current targeted service tests and Ruff with the development environment;
consult CI for the complete repository suite. The discovery/engagement build was
validated with 222 targeted tests and a fresh-channel Streamlit UI/relocation smoke
test. These software checks do not certify a particular movie's creative quality.
This documentation update makes no provider requests or social account changes.

## Licence and private configuration

The upstream [MIT licence](LICENSE) and notices remain in force. A configured
company copyright notice covers owner-declared original production elements only
to the extent protected; it does not claim ownership of folklore, third-party
assets, upstream software or provider trademarks. Source/adaptation, visual,
voice and music/ambience licences require their own evidence.

Keep commercial prompts, channel policy, credentials, account/billing information,
private media and review evidence outside this public repository. Private policy
may be restored for authorized projects; a public clone alone cannot reproduce
private assets, logins or historical approvals.


Production QA retains removed-shot receipts as history only when a saved earlier
Flow recipe proves the same shot ID and prompt hash. Every current shot still
requires its exact current recipe and media checks; unknown extra receipts remain
blocked. Plot-comparison sources may explicitly record `reference_only_not_reused`
with provenance notes. That research status never clears visual, voice, script or
music assets; their separate rights records remain mandatory.
