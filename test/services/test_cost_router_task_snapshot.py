import json
from unittest.mock import patch

from app.config import config
from app.models.schema import VideoParams
from app.services import task


def test_task_start_snapshots_router_flags_and_preserves_existing_task_id(tmp_path):
    override = tmp_path / "cost-router-overrides.json"
    override.write_text(json.dumps({"enabled": True, "cache_enabled": True, "candidates": []}), encoding="utf-8")
    old_config = dict(config.app)
    config.app.update({"openai_api_key": "existing-in-memory-value", "llm_provider": "openai"})
    params = VideoParams(video_subject="fixture", video_script="prewritten")
    try:
        with (
            patch.object(task.utils, "root_dir", return_value=str(tmp_path)),
            patch.object(task, "_run_pipeline", return_value={"status": "ok"}) as pipeline,
        ):
            result = task.start("existing-task-id", params, stop_at="script")
        assert result == {"status": "ok"}
        context = pipeline.call_args.kwargs["cost_context"]
        assert context["_cost_router_job_id"] == "existing-task-id"
        assert context["cost_router_enabled"] is True
        assert context["cost_router_cache_enabled"] is True
        assert context["openai_api_key"] == "existing-in-memory-value"
        assert pipeline.call_args.args[:2] == ("existing-task-id", params)
    finally:
        config.app.clear()
        config.app.update(old_config)
