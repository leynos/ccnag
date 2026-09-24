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
  of `make test`, ``cargo test`` or ``nextest run`` other than the doctest
  command;
- ``build-test`` runs the doctests, unconditionally;
- the coverage step leaves the doctests off, so the doctest step is not a
  repeat;
- the crate declares no feature, explicitly or through an optional
  dependency, which is what makes ``--all-features`` the coverage default.
"""

from __future__ import annotations

import pathlib
import re
import tomllib

import pytest
import yaml

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = REPOSITORY_ROOT / ".github" / "workflows"
DOCTEST_COMMAND = "cargo test --doc --workspace --all-features"
COVERAGE_ACTION = "leynos/shared-actions/.github/actions/generate-coverage@"
#: Variable assignments and options may precede the make target.
SUITE = re.compile(
    r"\bmake\s+((?:\S+=\S+|-\S+)\s+)*test(?![-\w])"
    r"|\bcargo\s+(\+\S+\s+)?test\b|\bnextest\s+run\b"
)
DEPENDENCY_TABLES = ("dependencies", "dev-dependencies", "build-dependencies")


def _steps() -> list[tuple[str, dict]]:
    """Return every step of every workflow, labelled by file and job."""
    found = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in (document.get("jobs") or {}).items():
            found.extend(
                (f"{path.name}/{job_name}", step) for step in job.get("steps") or []
            )
    return found


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
    ("command", "runs_suite"),
    [
        ("make test", True),
        ("make test WITH_ACT=1", True),
        ("make -j2 test", True),
        ("cargo nextest run --all-targets", True),
        ("cargo test --all-features", True),
        ("make test-workflow-contracts", False),
        ("make lint", False),
    ],
)
def test_the_suite_pattern(command: str, *, runs_suite: bool) -> None:
    """Recognize every spelling of a suite run, and nothing longer."""
    assert bool(SUITE.search(command)) is runs_suite, command


def test_no_step_runs_the_suite_outside_coverage() -> None:
    """Refuse any suite run other than the doctest step."""
    repeated = [
        (where, step.get("run"))
        for where, step in _steps()
        if SUITE.search(str(step.get("run", "")))
        and str(step.get("run", "")).strip() != DOCTEST_COMMAND
    ]
    assert not repeated, f"the suite runs outside coverage in {repeated!r}"


def test_build_test_runs_the_doctests_on_every_event() -> None:
    """Require one unconditional doctest step in ``build-test``."""
    doctests = [
        step
        for where, step in _steps()
        if where == "ci.yml/build-test"
        and str(step.get("run", "")).strip() == DOCTEST_COMMAND
    ]
    assert len(doctests) == 1, "build-test must run the doctests once"
    assert "if" not in doctests[0], "the doctest step must run on every event"


def test_coverage_leaves_the_doctests_off() -> None:
    """Keep the coverage step from repeating the doctest step."""
    coverage = [
        step
        for _where, step in _steps()
        if str(step.get("uses", "")).startswith(COVERAGE_ACTION)
    ]
    assert coverage, "expected a coverage step"
    for step in coverage:
        assert str((step.get("with") or {}).get("doctests", "false")) == "false"


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
    assert _declares_features({"target": {"cfg(unix)": {"dependencies": {"x": optional}}}})
    assert _declares_features({"features": {"extra": []}})
    assert not _declares_features({"dependencies": {"serde": {"version": "1"}}})
