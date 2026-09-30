"""Hold the hosted sccache lane's shape (developers' guide, "Compiler cache").

On a GitHub-hosted runner the shared `setup-rust` action saves its sccache
directory only on a push to `main`, and keys it on a discriminator that
defaults to the job id. So three things must hold, and each is judged by the
action's name and inputs, never by a revision the pin bump moves:

- every `setup-rust` step names `expect-cache: any`;
- the pull-request `build-test` step and the publisher's step (the only one that
  runs on a push to `main`) share one explicit discriminator, or the reader has
  no writer;
- the release job, which builds with `cross` in a container that receives
  neither `RUSTC_WRAPPER` nor `SCCACHE_PATH`, turns sccache off.
"""

from __future__ import annotations

import typing as typ

from codescene_environment_rules import Workflow, jobs

SETUP_RUST: typ.Final[str] = "leynos/shared-actions/.github/actions/setup-rust@"
READER: typ.Final[tuple[str, str]] = ("ci.yml", "build-test")
WRITER: typ.Final[tuple[str, str]] = ("coverage-main.yml", "coverage-upload")
RELEASE: typ.Final[str] = "release.yml"


def setup_steps(workflow: Workflow, job_id: str | None = None) -> list[dict]:
    """Return the `setup-rust` steps of a workflow, or of one of its jobs.

    Returns
    -------
    list[dict]
        Each step mapping that calls the shared action.

    """
    selected = jobs(workflow)
    if job_id is not None:
        selected = {job_id: selected[job_id]} if job_id in selected else {}
    return [
        step
        for job in selected.values()
        for step in job.get("steps", [])
        if isinstance(step, dict) and str(step.get("uses", "")).startswith(SETUP_RUST)
    ]


def _input(step: dict, name: str) -> object:
    """Return a step's `with:` input, treating a bare `with:` as empty."""
    return (step.get("with") or {}).get(name)


def sccache_violations(workflows: dict[str, Workflow]) -> list[str]:
    """List every way the workflows break the hosted sccache lane.

    Returns
    -------
    list[str]
        One message per breach; empty when the lane holds.

    """
    problems: list[str] = []
    for name, workflow in workflows.items():
        steps = setup_steps(workflow)
        problems += [
            f"{name}: a setup-rust step lacks `expect-cache: any`"
            for step in steps
            if _input(step, "expect-cache") != "any"
        ]
        if name == RELEASE:
            problems += [
                f"{name}: a cross build must set `use-sccache: 'false'`"
                for step in steps
                if str(_input(step, "use-sccache")).lower() != "false"
            ]
    reader = [
        _input(s, "sccache-cache-discriminator")
        for s in setup_steps(workflows[READER[0]], READER[1])
    ]
    writer = [
        _input(s, "sccache-cache-discriminator")
        for s in setup_steps(workflows[WRITER[0]], WRITER[1])
    ]
    if not reader or not writer:
        problems.append("the reader and the writer must each run setup-rust")
    elif not (set(reader) == set(writer) and len(set(reader)) == 1 and reader[0]):
        problems.append("reader and writer must share one explicit discriminator")
    return problems
