from pathlib import Path

import pytest

from workflow_compiler.ir import ApiBinding, ApiMappingResult, Workflow, WorkflowPlan, WorkflowStep
from workflow_compiler.map_apis import load_workflows
from workflow_compiler.pipeline import CompileInputError, plans_without_spec, run_compile

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "fixtures" / "openemr" / "openapi.yaml"
WORKFLOWS = ROOT / "fixtures" / "openemr" / "workflows.json"


def test_missing_video_and_workflows_raises() -> None:
    with pytest.raises(CompileInputError, match="video"):
        run_compile()


def test_workflows_without_spec_emits_unmapped_skills(tmp_path) -> None:
    result = run_compile(workflows=WORKFLOWS, out_dir=tmp_path)
    assert result["skills"]
    first = result["skills"][0]
    assert first["name"]
    assert "No OpenAPI spec was provided" in first["markdown"] or "no matching operations" in first["markdown"].lower() or "cannot be grounded" in first["markdown"]
    assert (tmp_path / "plans.json").is_file()
    assert list((tmp_path / "skills").glob("*/SKILL.md"))


def test_workflows_with_spec_uses_mapper(tmp_path) -> None:
    items = load_workflows(WORKFLOWS)

    def fake_map(workflows, spec, **_kwargs):
        first = workflows[0]
        return ApiMappingResult(
            spec_title="OpenEMR API",
            spec_version="8.4.0",
            spec_path=str(spec),
            workflows=[
                WorkflowPlan(
                    workflow_name=first.workflow_name,
                    goal=first.goal,
                    inputs_observed=first.inputs_observed,
                    apis=[
                        ApiBinding(
                            method="GET",
                            path="/api/patient",
                            purpose="Find the patient.",
                        )
                    ],
                )
            ],
        )

    result = run_compile(
        workflows=items[:1],
        spec=SPEC,
        out_dir=tmp_path,
        map_fn=fake_map,
    )
    markdown = result["skills"][0]["markdown"]
    assert "GET" in markdown
    assert "/api/patient" in markdown
    assert "/api/fee-sheet" not in markdown


def test_plans_without_spec_marks_steps_unmapped() -> None:
    workflow = Workflow(
        workflow_name="Demo",
        goal="Do a thing.",
        steps=[WorkflowStep(action="search_patient")],
        final_state="Done.",
    )
    mapping = plans_without_spec([workflow])
    assert mapping.workflows[0].apis == []
    assert mapping.workflows[0].unmapped[0].action == "search_patient"
