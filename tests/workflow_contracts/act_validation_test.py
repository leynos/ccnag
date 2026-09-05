"""Contract for the act-validation workflow.

The job runs ``make test`` on the runner, and the Makefile links with clang
and ``-fuse-ld=mold`` on Linux, so the job must install those linkers before
the tests run. The assertions match the install command itself, not a step
name, so a step that keeps its name but loses the package fails the test.
"""

from __future__ import annotations

import pathlib
import shlex

import yaml

WORKFLOW = (
    pathlib.Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "act-validation.yml"
)

TEST_COMMAND = "make test WITH_ACT=1"
REQUIRED_PACKAGES = {"clang", "lld", "mold"}


def _steps() -> list[dict]:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = document["jobs"]["act-validation"]
    return job["steps"]


def _run_tokens(step: dict) -> list[str]:
    """Shell-lex a step's ``run`` block, joining backslash continuations."""
    script = step.get("run")
    if not isinstance(script, str):
        return []
    return shlex.split(script.replace("\\\n", " "), comments=True)


def _installs_required_packages(step: dict) -> bool:
    """Whether the step's run block has an ``apt-get install`` naming every linker."""
    tokens = _run_tokens(step)
    for index, token in enumerate(tokens):
        if token != "apt-get":
            continue
        if index + 1 < len(tokens) and tokens[index + 1] == "install":
            packages = set()
            for candidate in tokens[index + 2 :]:
                if candidate in {"&&", "||", ";"}:
                    break
                if not candidate.startswith("-"):
                    packages.add(candidate)
            if REQUIRED_PACKAGES <= packages:
                return True
    return False


def test_linkers_are_installed_before_the_tests_run() -> None:
    """An apt-get install naming clang, lld and mold precedes ``make test``."""
    steps = _steps()
    install_indexes = [
        i for i, step in enumerate(steps) if _installs_required_packages(step)
    ]
    assert install_indexes, (
        "act-validation must run `apt-get install` naming clang, lld and mold: "
        "`make test` links with -fuse-ld=mold on Linux and the runner ships none of them"
    )
    test_indexes = [
        i
        for i, step in enumerate(steps)
        if TEST_COMMAND in _run_tokens(step)
        or step.get("run", "").strip() == TEST_COMMAND
    ]
    assert test_indexes, f"act-validation must run {TEST_COMMAND!r}"
    assert min(install_indexes) < min(test_indexes), (
        "the linker install step must come before the step that runs the tests"
    )
