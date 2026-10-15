from pathlib import Path

import yaml


WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "upstream-monitor.yml"


def test_conflicting_upstream_merge_fails_after_preserving_impact_report():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    inspect = workflow["jobs"]["inspect"]
    steps = inspect["steps"]
    upload_index = next(
        index for index, step in enumerate(steps) if step["name"] == "Upload impact report"
    )
    conflict_index = next(
        index
        for index, step in enumerate(steps)
        if step["name"] == "Fail run and request human conflict resolution"
    )
    conflict_step = steps[conflict_index]

    assert upload_index < conflict_index
    assert "mergeable != 'true'" in conflict_step["if"]
    assert "Human action required" in conflict_step["run"]
    assert "No review branch or PR was created" in conflict_step["run"]
    assert "exit 1" in conflict_step["run"]


def test_review_pr_requires_clean_merge_and_has_a_pre_push_conflict_guard():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    prepare = workflow["jobs"]["prepare-review"]
    steps = prepare["steps"]
    branch_step = next(
        step for step in steps if step["name"] == "Create review branch without force-pushing"
    )

    assert "mergeable == 'true'" in prepare["if"]
    assert branch_step["run"].index('if [ "$MERGEABLE" != true ]') < branch_step[
        "run"
    ].index('git switch --create')
    assert "refusing to create a review branch or PR" in branch_step["run"]
