"""Prove the release workflow's shape holds, and that each clause bites.

Each mutation edits a private copy of this repository's release workflow the
way a later change could, and asserts the clause meant to catch it does.
"""

from __future__ import annotations

import copy
import typing as typ
from pathlib import Path

import pytest

from codescene_environment_rules import Workflow, jobs, read_workflows
from release_workflow_rules import (
    LINKER_VARIABLE,
    MATRIX,
    build_step,
    legs,
    release_violations,
)

WORKFLOWS: typ.Final[Path] = (
    Path(__file__).resolve().parents[2] / ".github" / "workflows"
)


@pytest.fixture
def release() -> Workflow:
    """Return a private copy of the release workflow to mutate.

    Returns
    -------
    Workflow
        The parsed release workflow, safe to edit.

    """
    return copy.deepcopy(read_workflows(WORKFLOWS)["release.yml"])


def _leg(release: Workflow, target: str) -> dict:
    """Return the matrix leg for a target."""
    return next(leg for leg in legs(release) if leg["target"] == target)


def _reports(release: Workflow, fragment: str) -> bool:
    """Return whether some violation names a fragment."""
    return any(fragment in problem for problem in release_violations(release))


def test_repository_release_holds_the_shape(release: Workflow) -> None:
    """The shipped release workflow has no violation."""
    assert release_violations(release) == []


@pytest.mark.parametrize(
    ("target", "key", "value"),
    [
        ("x86_64-apple-darwin", "builder", "cross"),
        ("aarch64-apple-darwin", "builder", "cross"),
        ("aarch64-apple-darwin", "runner", "ubuntu-latest"),
        ("x86_64-unknown-linux-gnu", "builder", "cargo"),
        ("x86_64-pc-windows-gnu", "runner", "macos-latest"),
    ],
)
def test_a_leg_on_the_wrong_builder_or_runner_is_refused(
    release: Workflow, target: str, key: str, value: str
) -> None:
    """A leg moved off its expected builder or runner is refused."""
    _leg(release, target)[key] = value

    assert _reports(release, target)


@pytest.mark.parametrize("target", [row[0] for row in MATRIX])
def test_a_dropped_or_duplicated_leg_is_refused(release: Workflow, target: str) -> None:
    """A leg dropped from, or repeated in, the matrix is refused."""
    include = jobs(release)["build"]["strategy"]["matrix"]["include"]
    duplicated = copy.deepcopy(release)
    dup_include = jobs(duplicated)["build"]["strategy"]["matrix"]["include"]
    dup_include.append(copy.deepcopy(_leg(duplicated, target)))
    include[:] = [leg for leg in include if leg["target"] != target]

    assert _reports(release, target)
    assert _reports(duplicated, "exactly")
    assert _reports(duplicated, target)


@pytest.mark.parametrize(
    ("builder", "run"),
    [
        (
            "cargo",
            "cross +nightly-2026-08-13 build --release --target ${{ matrix.target }}",
        ),
        ("cross", "cargo build --release --target ${{ matrix.target }}"),
        (
            "cross",
            "cross +nightly-2026-08-13 build --release --target ${{ matrix.target }}",
        ),
        ("cargo", "cargo build --release --target ${{ matrix.target }}"),
    ],
)
def test_a_build_step_running_the_wrong_tool_is_refused(
    release: Workflow, builder: str, run: str
) -> None:
    """A compile step that runs the wrong tool, or drops the toolchain, is refused."""
    build_step(release, builder)["run"] = run  # type: ignore[index]

    assert _reports(release, f"the {builder} step")


@pytest.mark.parametrize("linker", ["clang", "", None])
def test_a_cross_leg_linked_by_a_missing_clang_is_refused(
    release: Workflow, linker: str | None
) -> None:
    """The cross step must override the clang linker the image lacks."""
    env = build_step(release, "cross")["env"]  # type: ignore[index]
    if linker is None:
        del env[LINKER_VARIABLE]
    else:
        env[LINKER_VARIABLE] = linker

    assert _reports(release, LINKER_VARIABLE)


@pytest.mark.parametrize("fail_fast", [None, True])
def test_a_failing_leg_may_not_cancel_the_rest(
    release: Workflow, fail_fast: bool | None
) -> None:
    """Only an explicit `fail-fast: false` keeps the other legs building."""
    strategy = jobs(release)["build"]["strategy"]
    if fail_fast is None:
        del strategy["fail-fast"]
    else:
        strategy["fail-fast"] = fail_fast

    assert _reports(release, "fail-fast")


@pytest.mark.parametrize(
    "dry_run",
    [None, {"type": "boolean", "default": False}, {"type": "string", "default": True}],
)
def test_a_dispatch_that_is_not_a_dry_run_by_default_is_refused(
    release: Workflow, dry_run: dict | None
) -> None:
    """The dispatch needs a boolean `dry-run` input that defaults to true."""
    trigger = release["on"] if "on" in release else release[True]
    inputs = {} if dry_run is None else {"dry-run": dry_run}
    trigger["workflow_dispatch"] = {"inputs": inputs}

    assert _reports(release, "dry-run")


@pytest.mark.parametrize(
    "condition",
    [
        "github.event_name == 'push' || github.event_name == 'workflow_dispatch'",
        "github.event_name == 'push' || (github.event_name == 'workflow_dispatch' "
        "&& inputs.dry-run == false)",
        "true",
    ],
)
def test_a_publish_job_that_can_run_on_a_branch_dispatch_is_refused(
    release: Workflow, condition: str
) -> None:
    """The release job publishes only for a tag push or a real tag dispatch."""
    jobs(release)["release"]["if"] = condition

    assert _reports(release, "publish")
