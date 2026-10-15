"""Local director-led workflow page. Every provider action is an explicit click."""

import json
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
)
from app.utils import utils


st.set_page_config(page_title="Director Studio", page_icon="🎬", layout="wide")
st.title("Director Studio")
st.caption("A resumable, local-first story workflow. Research and Flow generation remain manual unless you explicitly invoke a configured adapter.")
store = StudioStore()
active_profile = load_director_profile()
st.caption(f"Creative profile: {active_profile['profile_id']} · snapshot {active_profile['profile_sha256'][:12]} · {active_profile['profile_visibility']}")

with st.expander("Start one story", expanded=not bool(store.list_stories())):
    with st.form("new_story"):
        story_input = st.text_area("Story title, source URL, or retelling", height=110, placeholder="Enter one story idea, a source URL to research, or a retelling request.")
        with st.expander("Advanced preferences (optional)"):
            age_defaults = active_profile.get("creative_defaults", {}).get("initial_audience", {})
            age_min = st.number_input("Audience age from", min_value=0, max_value=18, value=int(age_defaults.get("age_min", 6)))
            age_max = st.number_input("Audience age to", min_value=int(age_min), max_value=18, value=int(age_defaults.get("age_max", 12)))
            fiction = st.selectbox("Story framing", ["unclassified", "historical_fiction", "folktale", "fiction", "documentary", "biography"])
            duration_default = int(active_profile.get("creative_defaults", {}).get("target_duration_seconds", 420))
            duration = st.number_input("Target duration (seconds)", min_value=60, max_value=3600, value=duration_default, step=30)
            language = st.text_input("Language", value=str(age_defaults.get("language", "en")))
            intended_made_for_kids = age_defaults.get("made_for_kids")
            intended_index = 1 if intended_made_for_kids is True else 2 if intended_made_for_kids is False else 0
            made_for_kids_choice = st.selectbox("Intended child-directed setting", ["Needs review", "Yes", "No"], index=intended_index)
            moral = st.text_input("Learning or moral intent")
            all_platforms = ["youtube_long", "youtube_short", "facebook_reels", "instagram_reels", "tiktok", "dailymotion", "rumble"]
            profile_targets = active_profile.get("packaging_defaults", {}).get("platform_targets", all_platforms)
            platforms = st.multiselect("Platform targets", all_platforms, default=[item for item in profile_targets if item in all_platforms])
        create = st.form_submit_button("Create local project")
        if create:
            try:
                story_input = story_input.strip()
                if not story_input:
                    raise ValueError("Enter a story idea, source URL, or retelling request")
                parsed = urlparse(story_input)
                slug = Path(parsed.path).stem.replace("-", " ").replace("_", " ").strip() if parsed.scheme and parsed.netloc else ""
                title = slug.title()[:80] or "Story research request" if parsed.scheme and parsed.netloc else story_input.splitlines()[0][:80]
                audience_intent = True if made_for_kids_choice == "Yes" else False if made_for_kids_choice == "No" else None
                result = store.create_story({
                    "title": title,
                    "premise": story_input,
                    "audience": {"age_min": int(age_min), "age_max": int(age_max), "language": language, "intended_made_for_kids": audience_intent},
                    "fiction_taxonomy": fiction,
                    "moral_or_learning_intent": moral,
                    "platform_targets": platforms,
                    "target_duration_seconds": int(duration),
                    "duration_policy": "new_story_target",
                })
                st.success(f"Created {result['story_id']}")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

stories = store.list_stories()
if not stories:
    st.info("Create a story to begin. New stories default to seven minutes; legacy imports preserve their measured duration.")
    st.stop()

options = {f"{item['title']} · {item['story_id'][:8]}": item["story_id"] for item in stories}
selected_label = st.selectbox("Project", list(options))
story_id = options[selected_label]
story = store.story(story_id)
st.caption(f"Target {story['requested_duration_seconds']} seconds · current state is persisted in SQLite")
status_columns = st.columns(len(PHASES))
for column, phase in zip(status_columns, PHASES):
    column.metric(phase.title(), story["phases"][phase]["status"])

tab_research, tab_creative, tab_flow, tab_qa, tab_assets = st.tabs(["Research", "Creative", "Flow handoff", "Quality", "Packaging"])
with tab_research:
    request_doc = research_request(story)
    st.warning("Research has not been fetched. This card is a request for evidence, not a research result.")
    st.json(request_doc)
    with st.form("evidence_form"):
        source = st.text_input("Source title or asset label")
        category = st.selectbox("Rights category", ["source_script_adaptation", "visual", "voice", "music_ambience"])
        citation = st.text_input("Canonical URL or citation")
        claim = st.text_area("Claim supported or asset description", height=70)
        rights = st.selectbox("Rights status", ["unknown", "original", "licensed", "public_domain", "cleared", "not_used"])
        confidence = st.selectbox("Evidence confidence", ["unreviewed", "low", "medium", "high", "not_applicable"])
        if st.form_submit_button("Save source / rights evidence"):
            try:
                eid = store.add_evidence(story_id, {"source": source, "category": category, "citation": citation, "claim": claim, "rights_status": rights, "confidence": confidence})
                st.success(f"Saved evidence {eid}")
            except Exception as exc:
                st.error(str(exc))
    evidence = store.evidence(story_id)
    if evidence:
        st.dataframe(evidence, use_container_width=True)

with tab_creative:
    st.caption("The API call below is explicit and uses the existing MoneyPrinter provider configuration and new-job cost-router snapshot. It drafts a screenplay only; editorial approval remains required.")
    st.code(json.dumps({"schema_version": 1, "roles": [{"role_id": "narrator", "name": "Narrator", "function": "guide", "voice_direction": ""}], "scenes": [{"scene_id": "scene-01", "setting": "", "visual_intent": "", "lines": [{"role_id": "narrator", "text": "", "delivery": ""}]}]}, ensure_ascii=False, indent=2), language="json")
    if st.button("Request screenplay draft", type="primary", disabled=not bool(store.evidence(story_id))):
        try:
            artifact = request_screenplay_draft(store, story_id, app_config=dict(config.app))
            st.success(f"Draft saved · SHA-256 {artifact['sha256']}")
            st.json(artifact["document"])
        except Exception as exc:
            st.error(f"Draft failed: {exc}")
    uploaded_script = st.file_uploader("Or import reviewed screenplay JSON", type=["json"], key="screenplay_json")
    if uploaded_script and st.button("Validate and import screenplay"):
        try:
            document = json.loads(uploaded_script.getvalue())
            issues = validate_screenplay(document)
            if issues:
                st.error("; ".join(issues))
            else:
                artifact = ingest_screenplay_document(store, story_id, document, source="manual import")
                st.success(f"Saved screenplay · SHA-256 {artifact['sha256']}")
        except Exception as exc:
            st.error(str(exc))
    storyboard_upload = st.file_uploader("Import storyboard JSON with shot prompts", type=["json"], key="storyboard_json")
    if storyboard_upload and st.button("Save storyboard for review"):
        try:
            board = json.loads(storyboard_upload.getvalue())
            artifact = ingest_storyboard_document(store, story_id, board, source="manual import")
            st.success(f"Saved storyboard · SHA-256 {artifact['sha256']}")
        except Exception as exc:
            st.error(str(exc))
    screenplay_ready = bool(store.latest_artifact(story_id, "screenplay")) and store.phase(story_id, "screenplay")["status"] == "complete"
    st.caption("Storyboard drafting is one explicit routed LLM request. It uses the validated screenplay and configured creative profile; voice synthesis and Flow generation remain manual/provider-specific steps.")
    if st.button("Request director-led storyboard draft", disabled=not screenplay_ready):
        try:
            artifact = request_storyboard_draft(store, story_id, app_config=dict(config.app))
            st.success(f"Draft saved for visual review · SHA-256 {artifact['sha256']}")
            st.json(artifact["document"])
        except Exception as exc:
            st.error(f"Storyboard draft failed: {exc}")

with tab_flow:
    st.warning("Flow uses a documented manual browser handoff. This page does not automate the account, submit jobs, or assume costs.")
    if st.button("Export manual Flow prompt bundle", disabled=store.latest_artifact(story_id, "storyboard") is None):
        try:
            bundle = export_flow_bundle(store, story_id)
            out_dir = Path(utils.storage_dir("story_studio/exports", create=True))
            out = out_dir / f"{story_id}-flow-bundle.json"
            out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            st.success(f"Exported {out}")
            st.download_button("Download Flow bundle", json.dumps(bundle, ensure_ascii=False, indent=2), file_name=out.name, mime="application/json")
        except Exception as exc:
            st.error(str(exc))
    st.caption("Receipts must bind the exported shot prompt hash and the exact imported asset hash. Unknown billing stays unknown. Account security warnings require a human hold and are never auto-retried.")
    receipt_file = st.file_uploader("Import a Flow receipt JSON", type=["json"], key="flow_receipt")
    if receipt_file:
        st.json(json.loads(receipt_file.getvalue()))
        st.info("Use the CLI receipt importer after placing the rendered asset at a stable local path; the browser upload does not change or move source media.")

with tab_qa:
    qa_master = st.text_input("Assembled master for hash-bound QA", key=f"qa_master_{story_id}")
    qa_upload = st.file_uploader("Import reviewer QA JSON bound to this master and script", type=["json"], key="quality_review_json")
    if qa_upload and st.button("Import passing QA attestations"):
        try:
            result = import_quality_review(store, story_id, json.loads(qa_upload.getvalue()), master_path=qa_master)
            st.success("Reviewer QA imported and hash checked" if result["passed"] else "QA remains blocked")
        except Exception as exc:
            st.error(str(exc))
    report = quality_report(store, story_id, master_path=qa_master or None)
    if report["passed"]:
        st.success("Structure, rights, current media hashes, and imported reviewer checks passed.")
    else:
        st.error("Quality gate is blocked")
    st.json(report)
    if st.button("Save QA report"):
        artifact = store.add_artifact(story_id, "quality_report", document=report)
        st.caption(f"Saved QA report SHA-256 {artifact['sha256']}")

with tab_assets:
    st.caption("Packages are drafts for manual platform review. No upload or publish action is performed.")
    master = st.text_input("Local verified master path")
    captions = st.text_input("Local captions path (optional)")
    audience_reviewed = st.checkbox("I reviewed audience age and child-directed settings for this story")
    made_for_kids_reviewed = st.selectbox("Platform child-directed setting (after review)", ["Needs review", "Yes", "No"])
    ai_reviewed = st.selectbox("Synthetic-media review", ["Needs review", "reviewed_not_required", "disclosed", "not_applicable"])
    targets = story["request"].get("platform_targets") or ["youtube_long", "youtube_short"]
    platform_assets = {}
    for platform in targets:
        with st.expander(f"{platform} variant and audience review"):
            asset_path = st.text_input(f"Verified {platform} asset path", key=f"asset_{story_id}_{platform}")
            variant_reviewed = st.checkbox("I reviewed this platform-specific variant", key=f"variant_{story_id}_{platform}")
            audience_asset_reviewed = st.checkbox("I reviewed this platform's audience controls", key=f"audience_{story_id}_{platform}")
            platform_assets[platform] = {"path": asset_path, "variant_reviewed": variant_reviewed, "audience_reviewed": audience_asset_reviewed}
    if st.button("Draft platform metadata", disabled=not bool(master)):
        try:
            package = build_platform_package(store, story_id, master_path=master, captions_path=captions or None, platforms=tuple(targets), human_review={"audience_reviewed": audience_reviewed, "made_for_kids_reviewed": True if made_for_kids_reviewed == "Yes" else False if made_for_kids_reviewed == "No" else None, "ai_realistic_content": None if ai_reviewed == "Needs review" else ai_reviewed, "platform_assets": platform_assets})
            st.json(package)
            st.warning("Review each platform’s audience controls, disclosures, variants, rights, title promise, captions, and current limits in its own publishing interface.")
        except Exception as exc:
            st.error(str(exc))
    current_package = store.latest_artifact(story_id, "platform_package")
    if current_package:
        package_doc = current_package["document"]
        st.caption(f"Package SHA-256: {package_doc.get('package_sha256')}")
        if package_doc.get("readiness", {}).get("required_checks_passed"):
            reviewer = st.text_input("Owner / reviewer name for local approval")
            if st.button("Approve exact package for manual handoff"):
                try:
                    master_artifact = store.latest_artifact(story_id, "master")
                    approval_id = approve_package(store, story_id, master_artifact["sha256"], package_doc["package_sha256"], reviewer.strip())
                    st.success(f"Approved exact package for manual handoff · {approval_id}")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        else:
            st.info("Approval is held until the exact media, rights, caption, audience, and per-platform variant checks pass.")
