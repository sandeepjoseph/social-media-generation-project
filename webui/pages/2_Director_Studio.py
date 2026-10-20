"""Local director-led workflow page. Every provider action is an explicit click."""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st

from app.config import config
from app.services.story_studio import (
    PHASES,
    StudioStore,
    build_platform_package,
    export_flow_bundle,
    ingest_screenplay_document,
    ingest_storyboard_document,
    import_quality_review,
    load_director_profile,
    quality_report,
    request_screenplay_draft,
    request_storyboard_draft,
    approve_package,
    research_request,
    validate_screenplay,
    profile_status,
    refresh_story_profile,
    record_learning_rule,
    import_performance_pilot_review,
    finishing_review_template,
)
from app.services.studio_cinema import policy_for
from app.services.studio_discovery import search_observation
from app.services.studio_native_movie import build_native_movie
from app.services.studio_native_finish import finish_saved_timeline
from app.services.studio_channel_setup import initialize_channel
from app.services.studio_captions import register_localized_variant
from app.utils import utils

st.set_page_config(page_title="Director Studio", page_icon="🎬", layout="wide")
st.title("Director Studio")
st.caption(
    "A resumable, local-first story workflow. Research and Flow generation remain manual unless you explicitly invoke a configured adapter."
)
store = StudioStore()
active_profile = load_director_profile()
active_cinema = policy_for(active_profile)
if active_cinema:
    st.info(
        f"Children's movie mode · ages 6–10 by default · full episodes {active_cinema['full_episode_min_seconds'] / 60:g}–{active_cinema['full_episode_max_seconds'] / 60:g} minutes · characters act and speak · lip-sync pilot required · Shorts are separate companions."
    )
    st.caption(
        f"Production template {active_profile.get('template_revision', 'unversioned')} · applied learning revision {active_profile.get('learning_rules', {}).get('revision', 0)}"
    )
    with st.expander("Production standards and saved improvements"):
        st.json(active_cinema)
        st.json(active_profile.get("learning_rules", {}))
        with st.form("production_learning"):
            learned_criterion = st.text_input(
                "Acceptance criterion",
                placeholder="e.g. dialogue, lip-sync, acting, duration, continuity",
            )
            learned_rule = st.text_area("Improvement for future productions")
            learned_applied = st.checkbox(
                "Apply this instruction to future projects", value=False
            )
            if st.form_submit_button("Save production learning"):
                try:
                    record_learning_rule(
                        text=learned_rule,
                        criterion_id=learned_criterion,
                        status="applied" if learned_applied else "experiment",
                    )
                    st.success(
                        "Saved locally. New projects load applied rules; experiments remain unproven."
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
st.caption(
    f"Creative profile: {active_profile['profile_id']} · snapshot {active_profile['profile_sha256'][:12]} · {active_profile['profile_visibility']}"
)
if active_profile.get("production_attribution"):
    with st.expander("Company credits, copyright and category defaults"):
        st.json(active_profile["production_attribution"])
        st.json(
            (active_profile.get("packaging_defaults") or {}).get(
                "platform_categories", {}
            )
        )
        st.caption(
            "Credits are inserted into every prepared description. Copyright applies to owner-declared original production elements to the extent protected; asset/source licences, audience and AI reviews are separate release gates. Category labels must be available in the current platform."
        )

with st.expander("Search and engagement defaults"):
    st.json(
        {
            "search_policy": active_profile.get("search_policy", {}),
            "engagement_policy": active_profile.get("engagement_policy", {}),
        }
    )
    st.caption(
        "Story relevance is checked before handoff; indexing and ranking need actual observations. Enable comments/publication notifications only where permitted. YouTube Made for Kids videos cannot enable either; viewer alert preferences remain their own."
    )

with st.expander("Set up a separate channel or another laptop"):
    st.caption(
        "Copies reusable production rules and credits into fresh private state. Connect that channel's own accounts and credentials after launch. Existing productions are not changed."
    )
    with st.form("separate_channel_setup"):
        channel_slug = st.text_input("New channel ID", placeholder="my-new-channel")
        channel_label = st.text_input("New channel name")
        channel_root = st.text_input(
            "New private channel folder",
            value=str(Path.home() / "StoryStudioChannels" / "new-channel"),
        )
        channel_owner = st.text_input(
            "Rights owner for original production elements",
            value=(active_profile.get("production_attribution") or {}).get(
                "rights_owner", ""
            ),
        )
        if st.form_submit_button("Create isolated channel setup"):
            try:
                initialized = initialize_channel(
                    channel_root,
                    channel_id=channel_slug,
                    channel_name=channel_label,
                    source_profile=os.environ.get("STORY_STUDIO_PROFILE_PATH"),
                    rights_owner=channel_owner or None,
                )
                st.success(
                    "Fresh channel setup saved. No accounts, credentials, approvals or media were copied."
                )
                st.json(initialized)
                st.code(
                    f'python -m app.services.studio_channel_setup launch --root "{initialized["channel_root"]}" --port 8512',
                    language="bash",
                )
            except Exception as exc:
                st.error(str(exc))

with st.expander("Start one story", expanded=not bool(store.list_stories())):
    with st.form("new_story"):
        story_input = st.text_area(
            "Story title, source URL, or retelling",
            height=110,
            placeholder="Enter one story idea, a source URL to research, or a retelling request.",
        )
        with st.expander("Advanced preferences (optional)"):
            age_defaults = active_profile.get("creative_defaults", {}).get(
                "initial_audience", {}
            )
            age_min = st.number_input(
                "Audience age from",
                min_value=0,
                max_value=18,
                value=int(age_defaults.get("age_min", 6)),
            )
            age_max = st.number_input(
                "Audience age to",
                min_value=int(age_min),
                max_value=18,
                value=int(age_defaults.get("age_max", 12)),
            )
            fiction = st.selectbox(
                "Story framing",
                [
                    "unclassified",
                    "historical_fiction",
                    "folktale",
                    "fiction",
                    "documentary",
                    "biography",
                ],
            )
            duration_default = int(
                active_profile.get("creative_defaults", {}).get(
                    "target_duration_seconds", 420
                )
            )
            duration = st.number_input(
                "Target duration (seconds)",
                min_value=int(active_cinema.get("full_episode_min_seconds", 60)),
                max_value=int(active_cinema.get("full_episode_max_seconds", 3600)),
                value=duration_default,
                step=30,
            )
            language = st.text_input(
                "Language", value=str(age_defaults.get("language", "en"))
            )
            intended_made_for_kids = age_defaults.get("made_for_kids")
            intended_index = (
                1
                if intended_made_for_kids is True
                else 2 if intended_made_for_kids is False else 0
            )
            made_for_kids_choice = st.selectbox(
                "Intended child-directed setting",
                ["Needs review", "Yes", "No"],
                index=intended_index,
            )
            moral = st.text_input("Learning or moral intent")
            all_platforms = [
                "youtube_long",
                "youtube_short",
                "facebook_reels",
                "instagram_reels",
                "tiktok",
                "dailymotion",
                "rumble",
            ]
            profile_targets = active_profile.get("packaging_defaults", {}).get(
                "platform_targets", all_platforms
            )
            platforms = st.multiselect(
                "Platform targets",
                all_platforms,
                default=[item for item in profile_targets if item in all_platforms],
            )
        create = st.form_submit_button("Create local project")
        if create:
            try:
                story_input = story_input.strip()
                if not story_input:
                    raise ValueError(
                        "Enter a story idea, source URL, or retelling request"
                    )
                parsed = urlparse(story_input)
                slug = (
                    Path(parsed.path).stem.replace("-", " ").replace("_", " ").strip()
                    if parsed.scheme and parsed.netloc
                    else ""
                )
                title = (
                    slug.title()[:80] or "Story research request"
                    if parsed.scheme and parsed.netloc
                    else story_input.splitlines()[0][:80]
                )
                audience_intent = (
                    True
                    if made_for_kids_choice == "Yes"
                    else False if made_for_kids_choice == "No" else None
                )
                result = store.create_story(
                    {
                        "title": title,
                        "premise": story_input,
                        "audience": {
                            "age_min": int(age_min),
                            "age_max": int(age_max),
                            "language": language,
                            "intended_made_for_kids": audience_intent,
                        },
                        "fiction_taxonomy": fiction,
                        "moral_or_learning_intent": moral,
                        "platform_targets": platforms,
                        "target_duration_seconds": int(duration),
                        "duration_policy": "new_story_target",
                    }
                )
                st.success(f"Created {result['story_id']}")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

stories = store.list_stories()
if not stories:
    st.info(
        "Create a story to begin. New stories default to seven minutes; legacy imports preserve their measured duration."
    )
    st.stop()

options = {
    f"{item['title']} · {item['story_id'][:8]}": item["story_id"] for item in stories
}
selected_label = st.selectbox("Project", list(options))
story_id = options[selected_label]
story = store.story(story_id)
version_status = profile_status(store, story_id)
if version_status["cinema_required"] and version_status["needs_replan"]:
    st.warning(
        "This project's frozen template is older than the current production standards. Generation and release are held until it is replanned. Existing source media stays preserved."
    )
    if st.button("Apply latest template and replan this project"):
        try:
            refresh_story_profile(store, story_id)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
st.caption(
    f"Target {story['requested_duration_seconds']} seconds · current state is persisted in SQLite"
)
status_columns = st.columns(len(PHASES))
for column, phase in zip(status_columns, PHASES):
    column.metric(phase.title(), story["phases"][phase]["status"])

tab_research, tab_creative, tab_flow, tab_qa, tab_assets = st.tabs(
    ["Research", "Creative", "Flow handoff", "Quality", "Packaging"]
)
with tab_research:
    request_doc = research_request(story)
    st.warning(
        "Research has not been fetched. This card is a request for evidence, not a research result."
    )
    st.json(request_doc)
    with st.form("evidence_form"):
        source = st.text_input("Source title or asset label")
        category = st.selectbox(
            "Rights category",
            ["source_script_adaptation", "visual", "voice", "music_ambience"],
        )
        citation = st.text_input("Canonical URL or citation")
        claim = st.text_area("Claim supported or asset description", height=70)
        rights = st.selectbox(
            "Rights status",
            ["unknown", "original", "licensed", "public_domain", "cleared", "not_used"],
        )
        confidence = st.selectbox(
            "Evidence confidence",
            ["unreviewed", "low", "medium", "high", "not_applicable"],
        )
        if st.form_submit_button("Save source / rights evidence"):
            try:
                eid = store.add_evidence(
                    story_id,
                    {
                        "source": source,
                        "category": category,
                        "citation": citation,
                        "claim": claim,
                        "rights_status": rights,
                        "confidence": confidence,
                    },
                )
                st.success(f"Saved evidence {eid}")
            except Exception as exc:
                st.error(str(exc))
    evidence = store.evidence(story_id)
    if evidence:
        st.dataframe(evidence, use_container_width=True)

with tab_creative:
    if active_cinema:
        st.info(
            "The JSON below illustrates the shape only. A complete film needs two speaking characters, the full dramatic arc, 6–8 minutes of meaningful scenes and the required character-performance fields; the validators enforce the complete package."
        )
    st.caption(
        "The API call below is explicit and uses the existing MoneyPrinter provider configuration and new-job cost-router snapshot. It drafts a screenplay only; editorial approval remains required."
    )
    st.code(
        json.dumps(
            {
                "schema_version": 1,
                "roles": [
                    {
                        "role_id": "character-a" if active_cinema else "narrator",
                        "name": "First character" if active_cinema else "Narrator",
                        "kind": "character" if active_cinema else "narrator",
                        "voice_id": "original-character-a",
                        "function": "pursues the scene objective",
                        "voice_direction": "",
                    }
                ],
                "scenes": [
                    {
                        "scene_id": "scene-01",
                        "setting": "",
                        "visual_intent": "",
                        "dramatic_purpose": "",
                        "action": "",
                        "story_beat": "setup",
                        "estimated_duration_seconds": 60,
                        "lines": [
                            {
                                "line_id": "line-01",
                                "role_id": (
                                    "character-a" if active_cinema else "narrator"
                                ),
                                "text": "",
                                "delivery": "",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        language="json",
    )
    if st.button(
        "Request screenplay draft",
        type="primary",
        disabled=not bool(store.evidence(story_id)),
    ):
        try:
            artifact = request_screenplay_draft(
                store, story_id, app_config=dict(config.app)
            )
            st.success(f"Draft saved · SHA-256 {artifact['sha256']}")
            st.json(artifact["document"])
        except Exception as exc:
            st.error(f"Draft failed: {exc}")
    uploaded_script = st.file_uploader(
        "Or import reviewed screenplay JSON", type=["json"], key="screenplay_json"
    )
    if uploaded_script and st.button("Validate and import screenplay"):
        try:
            document = json.loads(uploaded_script.getvalue())
            issues = validate_screenplay(document)
            if issues:
                st.error("; ".join(issues))
            else:
                artifact = ingest_screenplay_document(
                    store, story_id, document, source="manual import"
                )
                st.success(f"Saved screenplay · SHA-256 {artifact['sha256']}")
        except Exception as exc:
            st.error(str(exc))
    storyboard_upload = st.file_uploader(
        "Import storyboard JSON with shot prompts", type=["json"], key="storyboard_json"
    )
    if storyboard_upload and st.button("Save storyboard for review"):
        try:
            board = json.loads(storyboard_upload.getvalue())
            artifact = ingest_storyboard_document(
                store, story_id, board, source="manual import"
            )
            st.success(f"Saved storyboard · SHA-256 {artifact['sha256']}")
        except Exception as exc:
            st.error(str(exc))
    screenplay_ready = (
        bool(store.latest_artifact(story_id, "screenplay"))
        and store.phase(story_id, "screenplay")["status"] == "complete"
    )
    st.caption(
        "Storyboard drafting is one explicit routed LLM request. It uses the validated screenplay and configured creative profile; voice synthesis and Flow generation remain manual/provider-specific steps."
    )
    if st.button(
        "Request director-led storyboard draft", disabled=not screenplay_ready
    ):
        try:
            artifact = request_storyboard_draft(
                store, story_id, app_config=dict(config.app)
            )
            st.success(f"Draft saved for visual review · SHA-256 {artifact['sha256']}")
            st.json(artifact["document"])
        except Exception as exc:
            st.error(f"Storyboard draft failed: {exc}")

with tab_flow:
    if active_cinema:
        st.info(
            "Generate and review the two designated native-dialogue pilot shots first. Bulk generation stays held until the exact pilot clips pass wording, speaker identity, acting and full-utterance lip-sync review. A silent or narrator-only take cannot substitute."
        )
        pilot_file = st.file_uploader(
            "Two-character performance pilot review JSON",
            type=["json"],
            key="cinema_pilot",
        )
        if pilot_file and st.button("Import reviewed performance pilot"):
            try:
                import_performance_pilot_review(
                    store, story_id, json.loads(pilot_file.getvalue())
                )
                st.success(
                    "Pilot accepted for this exact storyboard and media. Re-export the Flow bundle to release its remaining shots."
                )
            except Exception as exc:
                st.error(str(exc))
    st.warning(
        "Flow uses a documented manual browser handoff. This page does not automate the account, submit jobs, or assume costs."
    )
    if st.button(
        "Export manual Flow prompt bundle",
        disabled=store.latest_artifact(story_id, "storyboard") is None,
    ):
        try:
            bundle = export_flow_bundle(store, story_id)
            out_dir = Path(utils.storage_dir("story_studio/exports", create=True))
            out = out_dir / f"{story_id}-flow-bundle.json"
            out.write_text(
                json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            st.success(f"Exported {out}")
            st.download_button(
                "Download Flow bundle",
                json.dumps(bundle, ensure_ascii=False, indent=2),
                file_name=out.name,
                mime="application/json",
            )
        except Exception as exc:
            st.error(str(exc))
    st.caption(
        "Receipts must bind the exported shot prompt hash and the exact imported asset hash. Unknown billing stays unknown. Account security warnings require a human hold and are never auto-retried."
    )
    current_bundle = store.latest_artifact(story_id, "flow_bundle")
    if current_bundle:
        from app.services.studio_provider_preflight import attest_submission

        st.subheader("Provider composer preflight")
        st.caption(
            "Enter observations from the actual provider UI after staging the shot. "
            "The complete prompt, actor, references, voice, native audio and one-output quote must match. "
            "This check does not submit generation or approve acting."
        )
        preflight_shots = current_bundle["document"]["shots"]
        selected_preflight = st.selectbox(
            "Staged shot",
            [shot["shot_id"] for shot in preflight_shots],
            key="preflight_shot",
        )
        actual_observation = st.text_area(
            "Actual provider observation JSON", value="{}", key="provider_observation"
        )
        preflight_key = f"provider_preflight:{story_id}"
        if st.button("Validate observed composer"):
            try:
                if profile_status(store, story_id)["needs_replan"]:
                    raise ValueError(
                        "Refresh and replan the changed production template first"
                    )
                selected = next(
                    s for s in preflight_shots if s["shot_id"] == selected_preflight
                )
                attestation = attest_submission(
                    selected,
                    json.loads(actual_observation),
                    story_id=story_id,
                    storyboard_sha256=current_bundle["document"]["storyboard_sha256"],
                )
                store.add_artifact(
                    story_id, "provider_submission_preflight", document=attestation
                )
                st.session_state[preflight_key] = {
                    "observation": actual_observation,
                    "bundle": current_bundle["sha256"],
                    "shot_id": selected_preflight,
                    "attestation": attestation,
                }
                st.success(
                    "Composer matches. Reserve its quoted cost separately before one Generate activation."
                )
            except Exception as exc:
                st.error(str(exc))
        validated = st.session_state.get(preflight_key, {})
        if (
            validated.get("observation") == actual_observation
            and validated.get("bundle") == current_bundle["sha256"]
            and validated.get("shot_id") == selected_preflight
        ):
            st.download_button(
                "Download submission attestation",
                json.dumps(validated["attestation"], ensure_ascii=False, indent=2),
                file_name=f"{story_id}-{selected_preflight}-submission-attestation.json",
                mime="application/json",
            )
    receipt_file = st.file_uploader(
        "Import a Flow receipt JSON", type=["json"], key="flow_receipt"
    )
    if receipt_file:
        st.json(json.loads(receipt_file.getvalue()))
        st.info(
            "Use the CLI receipt importer after placing the rendered asset at a stable local path; the browser upload does not change or move source media."
        )

with tab_qa:
    story_locale = str(story["request"].get("audience", {}).get("language", "en"))
    st.info(
        f"Captions must be fluent-reviewed and match the story target and spoken audio locale ({story_locale}). English captions cannot approve a Malayalam variant."
    )
    if active_cinema:
        with st.expander("Assemble reviewed character performances"):
            st.caption(
                "Uses each reviewed moving scene in story order with its original actor audio. "
                "A review cut allows full-sequence checks before the final music mix. "
                "Rendering never approves publication."
            )
            native_board = st.text_input(
                "Reviewed storyboard file", key=f"native_board_{story_id}"
            )
            native_selection = st.text_input(
                "Reviewed scene selection file", key=f"native_selection_{story_id}"
            )
            native_output = st.text_input(
                "New movie output path (.mp4)", key=f"native_output_{story_id}"
            )
            native_review = st.checkbox(
                "Build a review cut before the final sound mix",
                value=True,
                key=f"native_review_{story_id}",
            )
            native_font = st.text_input(
                "Verified caption font", value="Arial", key=f"native_font_{story_id}"
            )
            native_music = st.text_input(
                "Original or licensed music file (final mix)",
                key=f"native_music_{story_id}",
            )
            native_rights = st.text_input(
                "Music rights evidence file (final mix)",
                key=f"native_rights_{story_id}",
            )
            st.caption(
                "For caption/sound changes, reuse an existing verified native timeline to avoid another scene assembly or provider generation."
            )
            native_saved_record = st.text_input(
                "Saved native timeline receipt (optional)",
                key=f"native_saved_record_{story_id}",
            )
            native_saved_plan = st.text_input(
                "Its original selection plan (optional)",
                key=f"native_saved_plan_{story_id}",
            )
            native_cleanup = st.text_input(
                "Source-evidenced audio cleanup JSON (optional)",
                key=f"native_cleanup_{story_id}",
            )
            if st.button(
                "Build movie for review",
                disabled=not all([native_board, native_selection, native_output]),
            ):
                try:
                    if profile_status(store, story_id)["needs_replan"]:
                        raise ValueError(
                            "Apply the latest production template and explicitly replan before assembling"
                        )
                    current_board = store.latest_artifact(story_id, "storyboard")
                    supplied_board = json.loads(Path(native_board).read_text())
                    if not current_board or supplied_board != current_board["document"]:
                        raise ValueError("Use the current story's reviewed storyboard")
                    selected = json.loads(Path(native_selection).read_text())
                    if (
                        selected.get("storyboard_artifact_sha256")
                        != current_board["sha256"]
                    ):
                        raise ValueError(
                            "Scene selection must bind this exact storyboard artifact"
                        )
                    if selected.get("locale") != story_locale:
                        raise ValueError(
                            "Movie audio and captions must match this story's language"
                        )
                    receipts = {r["shot_id"]: r for r in store.flow_receipts(story_id)}
                    for entry in selected.get("shots", []):
                        slot = next(
                            (
                                s
                                for s in supplied_board["shots"]
                                if s["shot_id"] == entry["shot_id"]
                            ),
                            {},
                        )
                        if slot.get(
                            "speech_mode"
                        ) == "native_dialogue" and receipts.get(
                            entry["shot_id"], {}
                        ).get(
                            "asset_sha256"
                        ) != entry.get(
                            "sha256"
                        ):
                            raise ValueError(
                                "Import the exact reviewed native performance receipt before assembly"
                            )
                    with st.spinner("Assembling reviewed scenes and matching captions"):
                        if native_saved_record:
                            if not all(
                                [native_saved_plan, native_music, native_rights]
                            ):
                                raise ValueError(
                                    "Saved-timeline finishing requires the original plan and music rights"
                                )
                            result = finish_saved_timeline(
                                native_board,
                                native_selection,
                                native_saved_record,
                                native_saved_plan,
                                native_output,
                                music_path=native_music,
                                music_rights_path=native_rights,
                                caption_font=native_font,
                                cleanup=(
                                    json.loads(Path(native_cleanup).read_text())
                                    if native_cleanup
                                    else {}
                                ),
                            )
                        else:
                            result = build_native_movie(
                                native_board,
                                native_selection,
                                native_output,
                                review_cut=native_review,
                                music=native_music or None,
                                music_rights=native_rights or None,
                                caption_font=native_font,
                            )
                    delivery = []
                    for media in [result["master"], result["source_native_master"]]:
                        artifact = store.add_artifact(
                            story_id,
                            "generated_video",
                            path=media["path"],
                            provenance={
                                "source": "generated",
                                "locale": story_locale,
                                "publication_allowed": False,
                            },
                        )
                        delivery.append(artifact["provenance"].get("delivery_archive"))
                    for captions in result["captions"]:
                        artifact = store.add_artifact(
                            story_id,
                            "caption_track",
                            path=captions["path"],
                            provenance={
                                "locale": story_locale,
                                "publication_allowed": False,
                            },
                        )
                        delivery.append(artifact["provenance"].get("delivery_archive"))
                    result["delivery_archive"] = delivery
                    store.add_artifact(
                        story_id, "native_movie_candidate", document=result
                    )
                    st.success(
                        "Movie saved for audiovisual review. Publication remains subject to the Quality checks."
                    )
                    st.video(result["master"]["path"])
                except Exception as exc:
                    st.error(str(exc))
    qa_master = st.text_input(
        "Assembled master for hash-bound QA", key=f"qa_master_{story_id}"
    )
    with st.expander("Register master voice and caption variant"):
        master_caps_path = st.text_input(
            "Master SRT/VTT sidecar path", key=f"master_caps_{story_id}"
        )
        master_audio_locale = st.text_input(
            "Master audio BCP-47 locale",
            value=story_locale,
            key=f"master_audio_locale_{story_id}",
        )
        master_caption_locale = st.text_input(
            "Master caption BCP-47 locale",
            value=story_locale,
            key=f"master_caption_locale_{story_id}",
        )
        master_variant_id = st.text_input(
            "Master localized variant ID",
            value=f"master-{story_locale}",
            key=f"master_variant_{story_id}",
        )
        master_voice_status = st.selectbox(
            "Voice review status",
            ["Needs review", "reviewed", "not_used"],
            key=f"master_voice_status_{story_id}",
        )
        master_voice_id = st.text_input(
            "Voice name or ID (optional)", key=f"master_voice_id_{story_id}"
        )
        master_voice_provider = st.text_input(
            "Voice provider/model (or unknown)",
            value="unknown",
            key=f"master_voice_provider_{story_id}",
        )
        master_voice_audio_path = st.text_input(
            "Separate voice audio file path (optional; embedded video audio is also hash-bound)",
            key=f"master_voice_audio_{story_id}",
        )
        master_voice_reviewer = st.text_input(
            "Voice reviewer", key=f"master_voice_reviewer_{story_id}"
        )
        master_caption_reviewer = st.text_input(
            "Fluent caption reviewer", key=f"master_caption_reviewer_{story_id}"
        )
        master_burn_in_reviewed = st.checkbox(
            "I verified these captions are burned into the master video",
            key=f"master_burn_in_{story_id}",
        )
        master_burn_in_reviewer = st.text_input(
            "Burn-in reviewer", key=f"master_burn_in_reviewer_{story_id}"
        )
        if st.button(
            "Register hash-bound master variant",
            disabled=not bool(qa_master and master_caps_path),
        ):
            try:
                registered = register_localized_variant(
                    store,
                    story_id,
                    media_path=qa_master,
                    caption_path=master_caps_path,
                    variant_id=master_variant_id,
                    audio_locale=master_audio_locale,
                    caption_locale=master_caption_locale,
                    fluent_reviewer=master_caption_reviewer,
                    voice_record={
                        "locale": master_audio_locale,
                        "status": (
                            "not_used"
                            if master_voice_status == "not_used"
                            else (
                                "reviewed"
                                if master_voice_status == "reviewed"
                                else "needs_review"
                            )
                        ),
                        "voice_id": master_voice_id or None,
                        "provider": master_voice_provider,
                        "reviewer": master_voice_reviewer,
                        "audio_path": master_voice_audio_path or None,
                    },
                    burn_in_reviewed=master_burn_in_reviewed,
                    burn_in_reviewer=master_burn_in_reviewer,
                )
                st.success(
                    f"Caption/voice variant registered · {registered['variant']['caption_cue_count']} validated cues"
                )
                st.json(
                    registered["media_artifact"]["provenance"].get(
                        "delivery_archive", {}
                    )
                )
            except Exception as exc:
                st.error(str(exc))
    if active_cinema and qa_master:
        st.caption(
            "Mandatory final-film review: actual audio/video, every scene boundary, pleasant music, acting, continuity, readable captions and a complete ending. Label AI review and sampling limits honestly."
        )
        if st.button("Prepare unpassed finishing checklist"):
            try:
                checklist = finishing_review_template(store, story_id, qa_master)
                st.download_button(
                    "Download finishing review template",
                    json.dumps(checklist, indent=2),
                    file_name="finishing-review.pending.json",
                    mime="application/json",
                )
                st.info(
                    "Fill from actual final-film review and preserve evidence files. Include as finishing_review in the QA JSON; this template is not an approval."
                )
            except Exception as exc:
                st.error(str(exc))
    qa_upload = st.file_uploader(
        "Import reviewer QA JSON bound to this master and script",
        type=["json"],
        key="quality_review_json",
    )
    if qa_upload and st.button("Import passing QA attestations"):
        try:
            result = import_quality_review(
                store, story_id, json.loads(qa_upload.getvalue()), master_path=qa_master
            )
            st.success(
                "Reviewer QA imported and hash checked"
                if result["passed"]
                else "QA remains blocked"
            )
        except Exception as exc:
            st.error(str(exc))
    report = quality_report(store, story_id, master_path=qa_master or None)
    if report["passed"]:
        st.success(
            "Structure, rights, current media hashes, and imported reviewer checks passed."
        )
    else:
        st.error("Quality gate is blocked")
    st.json(report)
    if st.button("Save QA report"):
        artifact = store.add_artifact(story_id, "quality_report", document=report)
        st.caption(f"Saved QA report SHA-256 {artifact['sha256']}")

with tab_assets:
    st.caption(
        "Packages are drafts for manual platform review. Register a separate fluent-reviewed caption and voice record for every localized media variant. No upload or publish action is performed."
    )
    master = st.text_input("Local verified master path")
    st.caption(
        "Master captions are attached through the QA tab; platform variants require their own hash-bound caption and voice record below."
    )
    audience_reviewed = st.checkbox(
        "I reviewed audience age and child-directed settings for this story"
    )
    made_for_kids_reviewed = st.selectbox(
        "Platform child-directed setting (after review)", ["Needs review", "Yes", "No"]
    )
    ai_reviewed = st.selectbox(
        "Synthetic-media review",
        ["Needs review", "reviewed_not_required", "disclosed", "not_applicable"],
    )
    targets = story["request"].get("platform_targets") or [
        "youtube_long",
        "youtube_short",
    ]
    platform_assets = {}
    for platform in targets:
        with st.expander(f"{platform} variant and audience review"):
            asset_path = st.text_input(
                f"Verified {platform} asset path", key=f"asset_{story_id}_{platform}"
            )
            variant_reviewed = st.checkbox(
                "I reviewed this platform-specific variant",
                key=f"variant_{story_id}_{platform}",
            )
            audience_asset_reviewed = st.checkbox(
                "I reviewed this platform's audience controls",
                key=f"audience_{story_id}_{platform}",
            )
            platform_assets[platform] = {
                "path": asset_path,
                "variant_reviewed": variant_reviewed,
                "audience_reviewed": audience_asset_reviewed,
            }
            caption_path = st.text_input(
                f"{platform} SRT/VTT captions path", key=f"caps_{story_id}_{platform}"
            )
            audio_locale = st.text_input(
                f"{platform} audio BCP-47 locale",
                value=story_locale,
                key=f"audio_locale_{story_id}_{platform}",
            )
            caption_locale = st.text_input(
                f"{platform} caption BCP-47 locale",
                value=story_locale,
                key=f"caption_locale_{story_id}_{platform}",
            )
            variant_id = st.text_input(
                f"{platform} localized variant ID",
                value=f"{platform}-{story_locale}",
                key=f"variant_id_{story_id}_{platform}",
            )
            voice_status = st.selectbox(
                f"{platform} voice review status",
                ["Needs review", "reviewed", "not_used"],
                key=f"voice_status_{story_id}_{platform}",
            )
            voice_id = st.text_input(
                f"{platform} voice name or ID", key=f"voice_id_{story_id}_{platform}"
            )
            voice_provider = st.text_input(
                f"{platform} voice provider/model",
                value="unknown",
                key=f"voice_provider_{story_id}_{platform}",
            )
            voice_audio_path = st.text_input(
                f"{platform} separate voice audio file path (optional)",
                key=f"voice_audio_{story_id}_{platform}",
            )
            voice_reviewer = st.text_input(
                f"{platform} voice reviewer",
                key=f"voice_reviewer_{story_id}_{platform}",
            )
            caption_reviewer = st.text_input(
                f"{platform} fluent caption reviewer",
                key=f"caption_reviewer_{story_id}_{platform}",
            )
            burn_in_reviewed = st.checkbox(
                f"I verified the captions are burned into {platform}",
                key=f"burn_in_{story_id}_{platform}",
            )
            burn_in_reviewer = st.text_input(
                f"{platform} burn-in reviewer",
                key=f"burn_in_reviewer_{story_id}_{platform}",
            )
            if st.button(
                f"Register {platform} caption and voice variant",
                key=f"register_variant_{story_id}_{platform}",
                disabled=not bool(asset_path and caption_path),
            ):
                try:
                    registered = register_localized_variant(
                        store,
                        story_id,
                        media_path=asset_path,
                        caption_path=caption_path,
                        variant_id=variant_id,
                        audio_locale=audio_locale,
                        caption_locale=caption_locale,
                        fluent_reviewer=caption_reviewer,
                        voice_record={
                            "locale": audio_locale,
                            "status": (
                                "not_used"
                                if voice_status == "not_used"
                                else (
                                    "reviewed"
                                    if voice_status == "reviewed"
                                    else "needs_review"
                                )
                            ),
                            "voice_id": voice_id or None,
                            "provider": voice_provider,
                            "reviewer": voice_reviewer,
                            "audio_path": voice_audio_path or None,
                        },
                        burn_in_reviewed=burn_in_reviewed,
                        burn_in_reviewer=burn_in_reviewer,
                    )
                    st.success(
                        f"Registered captions and voice record · {registered['variant']['caption_cue_count']} cues"
                    )
                except Exception as exc:
                    st.error(str(exc))
    prepared_metadata_json = st.text_area(
        "Prepared publication metadata (JSON)",
        value="{}",
        key=f"metadata_{story_id}",
        help='Optional overrides: platform_titles, platform_descriptions, topics, keywords, chapters and search_brief. Example search_brief: {"primary_query": "main subject", "episode_query": "specific story phrase", "aliases": []}. Phrases must match the story or its configured spelling aliases. Cinema releases require prepared titles/descriptions for each selected platform. These become part of the exact approved package.',
    )
    if st.button("Draft platform metadata", disabled=not bool(master)):
        try:
            package = build_platform_package(
                store,
                story_id,
                master_path=master,
                platforms=tuple(targets),
                metadata=json.loads(prepared_metadata_json),
                human_review={
                    "audience_reviewed": audience_reviewed,
                    "made_for_kids_reviewed": (
                        True
                        if made_for_kids_reviewed == "Yes"
                        else False if made_for_kids_reviewed == "No" else None
                    ),
                    "ai_realistic_content": (
                        None if ai_reviewed == "Needs review" else ai_reviewed
                    ),
                    "platform_assets": platform_assets,
                },
            )
            st.json(package)
            st.warning(
                "Review each platform’s audience controls, disclosures, variants, rights, title promise, captions, and current limits in its own publishing interface."
            )
        except Exception as exc:
            st.error(str(exc))
    current_package = store.latest_artifact(story_id, "platform_package")
    if current_package:
        package_doc = current_package["document"]
        st.caption(f"Package SHA-256: {package_doc.get('package_sha256')}")
        with st.expander("YouTube search readiness and observed visibility"):
            st.caption(
                "Searchability and ranking are separate. These local checks make no provider calls and cannot force indexing. New uploads or edits can take a few days to appear."
            )
            for platform, item in package_doc.get("platforms", {}).items():
                discovery = item.get("search_readiness")
                if not discovery:
                    continue
                st.write(platform)
                st.json(discovery)
                st.link_button(
                    "Test story search in YouTube", discovery["search_test_url"]
                )
                st.download_button(
                    "Download search checklist",
                    json.dumps(discovery, indent=2, ensure_ascii=False),
                    file_name=f"{story_id}_{platform}_search-readiness.json",
                    mime="application/json",
                    key=f"search-download-{platform}",
                )
                observation_text = st.text_area(
                    "Actual search observation (JSON)",
                    value="{}",
                    key=f"search-observation-{story_id}-{platform}",
                    help="Record video_id, metadata_sha256 above, observed_at with timezone, query, context (sign-in/region/browser), evidence_reference, found and result_urls. Do not include account screenshots or credentials in the media archive.",
                )
                if st.button(
                    "Save observed search result", key=f"save-search-{platform}"
                ):
                    try:
                        observation = search_observation(
                            discovery, json.loads(observation_text)
                        )
                        store.add_artifact(
                            story_id,
                            "search_observation",
                            document={"platform": platform, **observation},
                            provenance={
                                "package_sha256": package_doc["package_sha256"]
                            },
                        )
                        st.success(
                            "Observed result saved separately from publication and creative approval."
                        )
                    except Exception as exc:
                        st.error(str(exc))
        with st.expander("Comments and publication notifications"):
            st.caption(
                "Defaults request comments and subscriber notifications where permitted. YouTube Made for Kids videos cannot enable either. Viewers control their own alerts; metadata preparation does not change live settings."
            )
            st.json(
                {
                    p: item.get("engagement_controls")
                    for p, item in package_doc.get("platforms", {}).items()
                }
            )
        if package_doc.get("readiness", {}).get("required_checks_passed"):
            reviewer = st.text_input("Owner / reviewer name for local approval")
            if st.button("Approve exact package for manual handoff"):
                try:
                    master_artifact = store.latest_artifact(story_id, "master")
                    approval_id = approve_package(
                        store,
                        story_id,
                        master_artifact["sha256"],
                        package_doc["package_sha256"],
                        reviewer.strip(),
                    )
                    st.success(
                        f"Approved exact package for manual handoff · {approval_id}"
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        else:
            st.info(
                "Approval is held until the exact media, rights, caption, audience, and per-platform variant checks pass."
            )
