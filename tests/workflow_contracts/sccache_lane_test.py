"""Prove the hosted sccache lane's shape holds, and that each clause bites.

Each mutation edits a private copy of this repository's workflows the way a
later change could, and asserts the clause meant to catch it does.
"""

from __future__ import annotations

import copy
import typing as typ
from pathlib import Path

import pytest

from codescene_environment_rules import Workflow, read_workflows
from sccache_lane_rules import (
    READER,
    RELEASE,
    WRITER,
    sccache_violations,
    setup_steps,
)

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


def _first_step(workflows: dict[str, Workflow], name: str, job: str | None) -> dict:
    """Return the first `setup-rust` step of a workflow's job."""
    return setup_steps(workflows[name], job)[0]


def test_repository_workflows_hold_the_lane(workflows: dict[str, Workflow]) -> None:
    """The shipped workflows have no sccache-lane violation."""
    assert sccache_violations(workflows) == []


def test_missing_expect_cache_is_refused(workflows: dict[str, Workflow]) -> None:
    """A setup step that drops `expect-cache` no longer names its backend."""
    del _first_step(workflows, *READER)["with"]["expect-cache"]

    assert any("expect-cache" in p for p in sccache_violations(workflows))


@pytest.mark.parametrize("side", [READER, WRITER], ids=["reader", "writer"])
def test_dropping_the_discriminator_on_one_side_is_refused(
    workflows: dict[str, Workflow], side: tuple[str, str]
) -> None:
    """A lane whose two ends differ leaves pull requests without a writer."""
    del _first_step(workflows, *side)["with"]["sccache-cache-discriminator"]

    assert any("discriminator" in p for p in sccache_violations(workflows))


def test_differing_discriminators_are_refused(
    workflows: dict[str, Workflow],
) -> None:
    """Two explicit but different values are two lanes."""
    _first_step(workflows, *WRITER)["with"]["sccache-cache-discriminator"] = "other"

    assert any("discriminator" in p for p in sccache_violations(workflows))


def test_release_with_sccache_on_is_refused(workflows: dict[str, Workflow]) -> None:
    """A cross build cannot reach the wrapper, so sccache must stay off."""
    del _first_step(workflows, RELEASE, None)["with"]["use-sccache"]

    assert any("cross" in p for p in sccache_violations(workflows))


def test_a_different_expect_cache_value_is_refused(
    workflows: dict[str, Workflow],
) -> None:
    """Naming a value other than `any` is not the recorded expectation."""
    _first_step(workflows, *READER)["with"]["expect-cache"] = "github"

    assert any("expect-cache" in p for p in sccache_violations(workflows))


def test_an_empty_shared_discriminator_is_refused(
    workflows: dict[str, Workflow],
) -> None:
    """Two empty values match, yet fall back to per-job lanes."""
    for side in (READER, WRITER):
        _first_step(workflows, *side)["with"]["sccache-cache-discriminator"] = ""

    assert any("discriminator" in p for p in sccache_violations(workflows))


def test_a_lane_without_a_writer_is_refused(workflows: dict[str, Workflow]) -> None:
    """A publisher that stops running setup-rust leaves nothing to save."""
    workflows[WRITER[0]]["jobs"][WRITER[1]]["steps"] = []

    assert any("must each run" in p for p in sccache_violations(workflows))
