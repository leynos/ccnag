"""Prove the parsed-workflow mold clause holds, and that each part of it bites.

Each mutation edits a private copy of this repository's workflows the way a
later change could, and asserts the clause meant to catch it does.
"""

from __future__ import annotations

import copy
import typing as typ
from pathlib import Path

import pytest

from build_standard_rules import INPUT, mold_violations
from codescene_environment_rules import Workflow, read_workflows
from sccache_lane_rules import RELEASE, READER, WRITER, setup_steps

WORKFLOWS: typ.Final[Path] = (
    Path(__file__).resolve().parents[2] / ".github" / "workflows"
)


@pytest.fixture
def workflows() -> dict[str, Workflow]:
    """Return a private copy of the repository's workflows to mutate.

    Returns
    -------
    dict[str, Workflow]
        The parsed workflows, safe to edit.

    """
    return copy.deepcopy(read_workflows(WORKFLOWS))


def _step(workflows: dict[str, Workflow], side: tuple[str, str]) -> dict:
    """Return the first `setup-rust` step of a workflow's job."""
    return setup_steps(workflows[side[0]], side[1])[0]


def test_repository_workflows_install_mold(workflows: dict[str, Workflow]) -> None:
    """The shipped workflows have no mold violation."""
    assert mold_violations(workflows) == []


def test_the_release_workflow_is_left_on_the_platform_linker(
    workflows: dict[str, Workflow],
) -> None:
    """The release build ships from the platform linker, so it passes no input."""
    release_steps = setup_steps(workflows[RELEASE])
    assert release_steps
    assert all(INPUT not in (step.get("with") or {}) for step in release_steps)
    assert mold_violations(workflows) == []


@pytest.mark.parametrize("side", [READER, WRITER], ids=["ci", "publisher"])
def test_a_step_that_drops_the_input_is_refused(
    workflows: dict[str, Workflow], side: tuple[str, str]
) -> None:
    """A setup step without the input leaves the linker uninstalled."""
    del _step(workflows, side)["with"][INPUT]

    assert any(INPUT in p for p in mold_violations(workflows))


@pytest.mark.parametrize("value", ["false", False, "", None, "yes"])
def test_a_step_that_turns_the_input_off_is_refused(
    workflows: dict[str, Workflow], value: object
) -> None:
    """Only `'true'` installs mold."""
    _step(workflows, READER)["with"][INPUT] = value

    assert any(INPUT in p for p in mold_violations(workflows))


def test_the_input_outside_with_is_refused(workflows: dict[str, Workflow]) -> None:
    """A key beside `uses:` is not an input, whatever `with:` says."""
    step = _step(workflows, READER)
    step[INPUT] = "true"

    assert any("beside `uses:`" in p for p in mold_violations(workflows))


def test_an_abbreviated_commit_is_refused(workflows: dict[str, Workflow]) -> None:
    """A short SHA is a prefix, not the full commit the pin must name."""
    step = _step(workflows, READER)
    step["uses"] = step["uses"].split("@", 1)[0] + "@" + step["uses"].split("@", 1)[1][:12]

    assert any("commit SHA" in p for p in mold_violations(workflows))


def test_a_floating_reference_is_refused(workflows: dict[str, Workflow]) -> None:
    """A branch or tag in place of a commit SHA is not the action's identity."""
    step = _step(workflows, READER)
    step["uses"] = step["uses"].split("@", 1)[0] + "@main"

    assert any("commit SHA" in p for p in mold_violations(workflows))


def test_a_sibling_step_cannot_lend_its_input(workflows: dict[str, Workflow]) -> None:
    """The input is judged on the step that sets up Rust, not on a neighbour."""
    steps = workflows[READER[0]]["jobs"][READER[1]]["steps"]
    index = steps.index(_step(workflows, READER))
    del steps[index]["with"][INPUT]
    steps.insert(index + 1, {"name": "Neighbour", "with": {INPUT: "true"}})

    assert any(INPUT in p for p in mold_violations(workflows))


def test_workflows_with_no_setup_step_prove_nothing(
    workflows: dict[str, Workflow],
) -> None:
    """Finding no step must not read as success."""
    for workflow in workflows.values():
        for job in workflow["jobs"].values():
            job["steps"] = []

    assert any("proves nothing" in p for p in mold_violations(workflows))
