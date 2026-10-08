"""Hold the release workflow's shape: every leg builds, macOS builds natively.

`cross` has no Docker image for Apple targets, so on a Linux runner it falls
back to host cargo, which lacks the target: the two Apple legs cannot build
there. They build natively on macOS runners, the other four keep `cross`, and
the `x86_64` Linux leg overrides `.cargo/config.toml`'s clang linker, which the
cross image lacks. A failed leg must not cancel the rest, and only a tag push,
or an explicit `dry-run: false` dispatch on a tag ref, publishes.
"""

from __future__ import annotations

import typing as typ

from codescene_environment_rules import Workflow, jobs

TOOLCHAIN: typ.Final[str] = "nightly-2026-08-13"
LINKER_VARIABLE: typ.Final[str] = "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER"
NATIVE_BUILD: typ.Final[str] = (
    f"cargo +{TOOLCHAIN} build --release --target ${{{{ matrix.target }}}}"
)
CROSS_BUILD: typ.Final[str] = "cross build --release --target ${{ matrix.target }}"
PUBLISH_IF: typ.Final[str] = (
    "github.event_name == 'push' || (github.event_name == 'workflow_dispatch' && "
    "inputs.dry-run == false && startsWith(github.ref, 'refs/tags/'))"
)
# Every release leg: its target, its builder and the runner it builds on.
MATRIX: typ.Final[tuple[tuple[str, str, str], ...]] = (
    ("x86_64-unknown-linux-gnu", "cross", "ubuntu-latest"),
    ("aarch64-unknown-linux-gnu", "cross", "ubuntu-latest"),
    ("x86_64-pc-windows-gnu", "cross", "ubuntu-latest"),
    ("x86_64-unknown-freebsd", "cross", "ubuntu-latest"),
    ("x86_64-apple-darwin", "cargo", "macos-15-intel"),
    ("aarch64-apple-darwin", "cargo", "macos-latest"),
)


def _get(node: object, *path: object) -> object:
    """Follow a path of keys and indices, returning None where it breaks."""
    for key in path:
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return None
    return node


def legs(workflow: Workflow) -> list[dict]:
    """Return the build matrix's legs.

    Returns
    -------
    list[dict]
        Each leg mapping, in declaration order.

    """
    include = _get(jobs(workflow).get("build"), "strategy", "matrix", "include")
    return (
        [leg for leg in include if isinstance(leg, dict)]
        if isinstance(include, list)
        else []
    )


def build_step(workflow: Workflow, builder: str) -> dict | None:
    """Return the build job's compile step guarded for one builder.

    Returns
    -------
    dict | None
        The step mapping, or None when absent.

    """
    steps = _get(jobs(workflow).get("build"), "steps")
    guard = f"matrix.builder == '{builder}'"
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, dict):
            continue
        is_build = "build --release" in str(step.get("run", ""))
        if step.get("if") == guard and is_build:
            return step
    return None


def _squeeze(value: object) -> str:
    """Collapse whitespace so a folded scalar compares as one line."""
    return " ".join(str(value).split())


def matrix_problems(workflow: Workflow) -> list[str]:
    """List the reasons the matrix is not exactly the six expected legs.

    Returns
    -------
    list[str]
        One message per breach.

    """
    found = legs(workflow)
    problems = []
    for target, builder, runner in MATRIX:
        matching = [leg for leg in found if leg.get("target") == target]
        is_expected = len(matching) == 1 and (
            matching[0].get("builder") == builder
            and matching[0].get("runner") == runner
        )
        if not is_expected:
            problems.append(
                f"{target} must appear once, built by {builder} on {runner}"
            )
    if len(found) != len(MATRIX):
        problems.append(f"the matrix must hold exactly {len(MATRIX)} legs")
    return problems


def publish_problems(workflow: Workflow) -> list[str]:
    """List the reasons the dispatch or publish job could publish by accident.

    Returns
    -------
    list[str]
        One message per breach.

    """
    problems = []
    trigger = workflow.get("on", workflow.get(True))
    dry_run = _get(trigger, "workflow_dispatch", "inputs", "dry-run")
    is_default_dry = (
        isinstance(dry_run, dict)
        and dry_run.get("type") == "boolean"
        and dry_run.get("default") is True
    )
    if not is_default_dry:
        problems.append("dispatch needs a boolean `dry-run` input defaulting to true")
    publish_if = _get(jobs(workflow).get("release"), "if")
    if _squeeze(publish_if) != PUBLISH_IF:
        problems.append(
            "the release job must publish only for a tag push or a real dispatch"
        )
    return problems


def release_violations(workflow: Workflow) -> list[str]:
    """List every way the workflow breaks the release shape.

    Returns
    -------
    list[str]
        One message per breach; empty when the shape holds.

    """
    problems = matrix_problems(workflow) + publish_problems(workflow)
    for builder, expected in (("cargo", NATIVE_BUILD), ("cross", CROSS_BUILD)):
        step = build_step(workflow, builder)
        if step is None or _squeeze(step.get("run")) != expected:
            problems.append(f"the {builder} step must run `{expected}`")
    cross = build_step(workflow, "cross")
    if _get(cross, "env", LINKER_VARIABLE) != "cc":
        problems.append(f"the cross step must set {LINKER_VARIABLE}=cc")
    if _get(jobs(workflow).get("build"), "strategy", "fail-fast") is not False:
        problems.append("fail-fast must be false so one leg cannot cancel the rest")
    return problems
