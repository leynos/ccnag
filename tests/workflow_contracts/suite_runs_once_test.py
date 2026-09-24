"""Contract that each pull request runs the test suite once.

`make test` runs nextest with ``--all-targets --all-features`` and then the
doctests. The coverage step in ``ci.yml`` runs the same tests, since the
crate declares no features and has no examples or benches, but not the
doctests. The repository used to carry an ``act-validation.yml`` workflow
running ``make test WITH_ACT=1``; nothing reads ``WITH_ACT`` and no test is
gated on Act, so it ran the whole suite a second time on every pull request
and was removed.

These tests hold the split:

- no workflow step runs the suite outside the coverage step, in any spelling
  of ``make test``, ``make all``, ``cargo test``, ``cargo nextest`` or
  ``cargo llvm-cov``, options before the subcommand included, except the one
  doctest step in ``build-test``;
- ``build-test`` runs, with no job-level condition, the doctests and the
  coverage action, each in one unconditional step;
- the coverage step passes only the inputs this repository has always passed.
  The pinned action declares no doctest input, so the doctest step is not a
  repeat;
- the crate declares no feature, explicitly or through an optional
  dependency, which is what makes ``--all-features`` the coverage default.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import tomllib
import yaml

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = REPOSITORY_ROOT / ".github" / "workflows"
DOCTEST_COMMAND = "cargo test --doc --workspace --all-features"
COVERAGE_ACTION = "leynos/shared-actions/.github/actions/generate-coverage@"
SUITE_JOB = "ci.yml/build-test"
#: The coverage inputs this repository passes. The pinned action declares no
#: doctest input, so the contract holds the inputs to this set rather than
#: asserting an input the action would ignore.
COVERAGE_INPUTS = frozenset({"output-path", "format", "with-ratchet"})
CARGO_VALUE_OPTIONS = frozenset(
    {"--config", "-Z", "-C", "--manifest-path", "--color", "--target-dir"}
)
MAKE_VALUE_OPTIONS = frozenset(
    {"-C", "-f", "-I", "-o", "-W", "--directory", "--file", "--makefile"}
)
SUITE_SUBCOMMANDS = frozenset({"test", "nextest", "llvm-cov"})
SUITE_TARGETS = frozenset({"test", "all"})
SEPARATORS = re.compile(r"&&|\|\||[;|\n]")
DEPENDENCY_TABLES = ("dependencies", "dev-dependencies", "build-dependencies")


def _jobs() -> list[tuple[str, dict]]:
    """Return every job of every workflow, labelled by file and job."""
    found = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        found.extend(
            (f"{path.name}/{name}", job)
            for name, job in (document.get("jobs") or {}).items()
        )
    return found


def _steps() -> list[tuple[str, dict]]:
    """Return every step of every workflow, labelled by file and job."""
    return [(where, step) for where, job in _jobs() for step in job.get("steps") or []]


def _operands(words: list[str], value_options: frozenset[str]) -> list[str]:
    """Return a command's operands: its words less options and their values."""
    found: list[str] = []
    skip = False
    for word in words:
        if skip:
            skip = False
        elif word in value_options:
            skip = True
        elif not word.startswith(("-", "+")) and "=" not in word:
            found.append(word)
    return found


def _arguments_of(words: list[str], program: str) -> list[str] | None:
    """Return the words after ``program`` in one shell segment, if it runs."""
    for index, word in enumerate(words):
        if word == program or word.endswith(f"/{program}"):
            return words[index + 1 :]
    return None


def _segment_runs_suite(words: list[str]) -> bool:
    """Report whether one shell segment runs the suite."""
    cargo = _arguments_of(words, "cargo")
    make = _arguments_of(words, "make")
    cargo_operands = _operands(cargo, CARGO_VALUE_OPTIONS) if cargo else []
    make_operands = _operands(make, MAKE_VALUE_OPTIONS) if make else []
    return (cargo_operands[:1] and cargo_operands[0] in SUITE_SUBCOMMANDS) or bool(
        SUITE_TARGETS & set(make_operands)
    )


def runs_suite(command: str) -> bool:
    """Report whether a shell command runs the suite, in any spelling.

    Examples
    --------
    >>> runs_suite("cargo --config tools/dev-fast/config.toml test")
    True
    >>> runs_suite("cargo run -- test")
    False
    """
    return any(
        _segment_runs_suite(segment.split()) for segment in SEPARATORS.split(command)
    )


def _dependency_tables(manifest: dict) -> list[object]:
    """Return every dependency table, top-level and target-specific."""
    tables = [manifest.get(name) for name in DEPENDENCY_TABLES]
    for platform in (manifest.get("target") or {}).values():
        tables.extend(platform.get(name) for name in DEPENDENCY_TABLES)
    return tables


def _declares_features(manifest: dict) -> bool:
    """Report whether a manifest has explicit or implicit features.

    Cargo turns each optional dependency into an implicit feature, so a crate
    with one has features even without a ``[features]`` table.
    """
    optional = [
        name
        for table in _dependency_tables(manifest)
        if isinstance(table, dict)
        for name, spec in table.items()
        if isinstance(spec, dict) and spec.get("optional") is True
    ]
    return bool(manifest.get("features")) or bool(optional)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("make test", True),
        ("make test WITH_ACT=1", True),
        ("make -j2 test", True),
        ("make -C . test", True),
        ("make all", True),
        ("cargo nextest run --all-targets", True),
        ("cargo test --all-features", True),
        ("cargo --config tools/dev-fast/config.toml test", True),
        ("cargo +nightly test", True),
        ("cargo llvm-cov nextest --lcov", True),
        ("set -eu && make test", True),
        ("make test-workflow-contracts", False),
        ("make lint", False),
        ("cargo build --all-targets", False),
        ("cargo run -- test", False),
    ],
)
def test_the_suite_pattern(command: str, *, expected: bool) -> None:
    """Recognize every spelling of a suite run, and nothing longer."""
    assert runs_suite(command) is expected, command


def test_only_the_doctest_step_runs_the_suite_outside_coverage() -> None:
    """Refuse any suite run but one doctest run in ``build-test``."""
    runs = [
        (where, str(step.get("run", "")).strip())
        for where, step in _steps()
        if runs_suite(str(step.get("run", "")))
    ]
    doctests = [run for run in runs if run == (SUITE_JOB, DOCTEST_COMMAND)]
    repeated = [run for run in runs if run != (SUITE_JOB, DOCTEST_COMMAND)]
    assert not repeated, f"the suite runs outside coverage in {repeated!r}"
    assert len(doctests) == 1, "the doctests must run once, in build-test"


def _suite_job() -> dict:
    """Return ``ci.yml``'s ``build-test`` job, refusing a conditional one."""
    job = dict(_jobs()).get(SUITE_JOB)
    assert job is not None, "ci.yml must define build-test"
    assert "if" not in job, "build-test must run on every pull request"
    return job


def test_build_test_runs_the_doctests_on_every_event() -> None:
    """Require one unconditional doctest step in an unconditional ``build-test``."""
    doctests = [
        step
        for step in _suite_job().get("steps") or []
        if str(step.get("run", "")).strip() == DOCTEST_COMMAND
    ]
    assert len(doctests) == 1, "build-test must run the doctests once"
    assert "if" not in doctests[0], "the doctest step must run on every event"


def test_build_test_runs_coverage_on_every_event() -> None:
    """Require one unconditional coverage step, with only the known inputs."""
    coverage = [
        step
        for step in _suite_job().get("steps") or []
        if str(step.get("uses", "")).startswith(COVERAGE_ACTION)
    ]
    assert len(coverage) == 1, "build-test must run the coverage action once"
    assert "if" not in coverage[0], "the coverage step must run on every event"
    inputs = set(coverage[0].get("with") or {})
    assert inputs == COVERAGE_INPUTS, (
        f"coverage inputs changed to {sorted(inputs)}; recheck what it runs"
    )


def test_the_crate_declares_no_features() -> None:
    """Refuse a feature, which would split ``--all-features`` from the default."""
    manifest = tomllib.loads((REPOSITORY_ROOT / "Cargo.toml").read_text("utf-8"))
    assert not _declares_features(manifest), (
        "Cargo.toml declares features; recheck make test against coverage"
    )


def test_an_optional_dependency_counts_as_a_feature() -> None:
    """Treat optional dependencies, in any dependency table, as features."""
    optional = {"optional": True, "version": "1"}
    assert _declares_features({"dependencies": {"serde": optional}})
    assert _declares_features(
        {"target": {"cfg(unix)": {"dependencies": {"x": optional}}}}
    )
    assert _declares_features({"features": {"extra": []}})
    assert not _declares_features({"dependencies": {"serde": {"version": "1"}}})
