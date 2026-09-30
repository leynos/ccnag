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
  ``suite_commands`` recognizes, except the one doctest step in
  ``build-test``;
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
import tomllib

import pytest
import yaml
from suite_commands import default_goal, runs_suite

REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = REPOSITORY_ROOT / ".github" / "workflows"
DOCTEST_COMMAND = "cargo test --doc --workspace --all-features"
COVERAGE_ACTION = "leynos/shared-actions/.github/actions/generate-coverage@"
#: The Makefile's DEV_RUST_FLAGS and RUSTDOC_FLAGS, which `make test` gives its
#: doctest line. Both restate Polonius, because an assigned value replaces
#: `.cargo/config.toml`'s flags.
DOCTEST_ENV = {
    "RUSTFLAGS": "-D warnings -Zpolonius=next -C link-arg=-fuse-ld=mold",
    "RUSTDOCFLAGS": "--cfg docsrs -D warnings -Zpolonius=next",
}
#: The default goal the spelling cases assume: one that runs the suite.
SUITE_GOAL = "all"
SUITE_JOB = "ci.yml/build-test"
#: The coverage inputs this repository passes. The pinned action declares no
#: doctest input, so the contract holds the inputs to this set rather than
#: asserting an input the action would ignore.
COVERAGE_INPUTS = frozenset({"output-path", "format", "with-ratchet"})
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
        ("make", True),
        ('make "test"', True),
        ("make coverage", True),
        ("make lint&&make test", True),
        ("RUSTFLAGS='-D warnings' cargo test", True),
        ("env RUN_ACT_VALIDATION=1 make test", True),
        ("make \\\ntest", True),
        ("make lint # then\nmake test", True),
        ("make test-workflow-contracts", False),
        ("make lint", False),
        ("cargo build --all-targets", False),
        ("cargo run -- test", False),
        ("echo cargo test", False),
        ("echo 'pre;make test;post'", False),
        ("# make test", False),
        ("if true; then cargo test; fi", True),
        ("(cd crate && cargo test)", True),
        ("timeout 30m make test", True),
        ("bash -c 'cargo test'", True),
        ("NAME=foo#bar make test", True),
        ("make test#notes", False),
        ("bash scripts/check.sh", False),
        ("nohup cargo test", True),
        ("sudo -u ci make test", True),
        ("bash -lc 'make test'", True),
        ("sh -ec 'make test'", True),
        ("bash -c 'cargo' test", False),
        ("make -j 4", True),
        ("make -l 4", True),
        ("make -j test", True),
        ("make -j lint", False),
        ("make >suite.log", True),
        ("make >> suite.log 2>&1", True),
        ("make 2> err.log test", True),
        ("make test > out.log", True),
        ("make lint > suite.log", False),
        ('make ">x"', False),
        ("make < in.txt lint", False),
        ("command pytest -v", True),
        ("command -v pytest", False),
        ("pytest --collect-only", False),
        ("pytest --co -q", False),
        ("pytest --help", False),
        ("pytest --version", False),
        ("python -m pytest --fixtures", False),
        ("uv run pytest --markers", False),
        ("uvx pytest --collect-only", False),
        ("timeout 5m pytest --setup-plan", False),
        ("pytest -q tests", True),
        ("cargo te\\\nst", True),
        ("make\\\ntest", False),
        ("make -j 4 lint", False),
        ("make --jobs 4", True),
        ('echo "a \\" ; make test"', False),
        ('echo "a \\" b" ; make test', True),
        ("pytest tests", True),
        ("py.test", True),
        ("python -m pytest", True),
        ("python3.13 -m pytest", True),
        ("uvx pytest", True),
        ("uv run pytest", True),
        ("uv run --with pytest python -m pytest", True),
        ("python script.py", False),
        ("make dev-test", True),
        ("make test-fast", True),
        ("echo 'make test", False),
        ('make "test', True),
        ("", False),
        ("&", False),
        ("make -n", False),
        ("make -ns", False),
        ("make --help", False),
        ("command -v make", False),
        ("uv run --directory . cargo test", True),
        ("echo ok # ; make test", False),
    ],
)
def test_the_suite_pattern(command: str, *, expected: bool) -> None:
    """Recognize every spelling of a suite run, and nothing longer."""
    assert runs_suite(command, SUITE_GOAL) is expected, command


@pytest.mark.parametrize(
    "prefix",
    [
        "env -u HOME",
        "timeout -s KILL 5m",
        "nice -n 5",
        "command",
        "exec -a name",
        "nohup",
        "setsid",
        "stdbuf -oL",
        "sudo -u ci",
        "uv run --directory .",
    ],
)
def test_every_wrapper_is_looked_through(prefix: str) -> None:
    """Look through each wrapper, with an option of its own, to its command."""
    assert runs_suite(f"{prefix} make test", SUITE_GOAL), prefix
    assert not runs_suite(f"{prefix} make lint", SUITE_GOAL), prefix


@pytest.mark.parametrize(
    ("goal", "expected"), [("build", False), ("all", True), ("test", True)]
)
def test_a_bare_make_runs_the_default_goal(goal: str, *, expected: bool) -> None:
    """Read a bare ``make`` as a suite run only when the default goal is one."""
    assert runs_suite("make", goal) is expected


@pytest.mark.parametrize(
    ("makefile", "expected"),
    [
        (".PHONY: a\nbuild: x\nall: y\n", "build"),
        (".DEFAULT_GOAL := test\nbuild:\n", "test"),
        (".DEFAULT_GOAL ?= test\nbuild:\n", "test"),
        (".DEFAULT_GOAL += test\nbuild:\n", "test"),
        (".DEFAULT_GOAL = test\nbuild:\n", "test"),
        (".DEFAULT_GOAL := first\n.DEFAULT_GOAL := second\nbuild:\n", "second"),
        (".DEFAULT_GOAL := first\n.DEFAULT_GOAL ?= second\nbuild:\n", "first"),
        (".DEFAULT_GOAL ?= second\n.DEFAULT_GOAL := first\nbuild:\n", "first"),
        (".DEFAULT_GOAL := build\nlint:\n.DEFAULT_GOAL := test\n", "test"),
        (".DEFAULT_GOAL := first\n.DEFAULT_GOAL :=\nbuild:\n", "build"),
        (".DEFAULT_GOAL := first\n.DEFAULT_GOAL += second\nbuild:\n", "build"),
        (".DEFAULT_GOAL   :=   spaced\nbuild:\n", "spaced"),
        ("first:\n\t.DEFAULT_GOAL = test\n", "first"),
        ("# build: not a rule\nrun: z\n", "run"),
        (".PHONY: a\n.SUFFIXES:\nrun: z\n", "run"),
        ("X := 1\n\tfoo: bar\n%.o: %.c\nrun: z\n", "run"),
        ("X := 1\n", ""),
    ],
)
def test_the_default_goal_is_read(makefile: str, expected: str) -> None:
    """Read the default goal the way make does."""
    assert default_goal(makefile) == expected


def test_only_the_doctest_step_runs_the_suite_outside_coverage() -> None:
    """Refuse any suite run but one doctest run in ``build-test``."""
    goal = default_goal((REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8"))
    runs = [
        (where, str(step.get("run", "")).strip())
        for where, step in _steps()
        if runs_suite(str(step.get("run", "")), goal)
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
    assert doctests[0].get("env") == DOCTEST_ENV, (
        "the doctest step must carry the flags `make test` gives its doctest line"
    )


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


@pytest.mark.parametrize(
    "target", ["test", "all", "coverage", "dev-test", "test-fast"]
)
def test_every_suite_target_runs_the_suite(target: str) -> None:
    """Read each suite target as a suite run, and a longer name as none."""
    assert runs_suite(f"make {target}", "build")
    assert runs_suite(f"make -j 4 {target}", "build")
    assert not runs_suite(f"make {target}-not", "build")


@pytest.mark.parametrize(
    "option",
    [
        "--just-print",
        "--dry-run",
        "--recon",
        "-n",
        "--question",
        "-q",
        "--help",
        "--version",
        "-v",
        "-ns",
    ],
)
def test_every_inert_make_option_runs_no_goal(option: str) -> None:
    """Refuse to read a make option that runs no goal as a suite run."""
    assert not runs_suite(f"make {option}", "all")
    assert not runs_suite(f"make {option} test", "all")
    assert not runs_suite(f"make test {option}", "all")


@pytest.mark.parametrize(
    "line", ["command -v make test", "command -V make test", "command -V make"]
)
def test_command_lookup_runs_nothing(line: str) -> None:
    """Read `command -v` and `command -V` as running nothing."""
    assert not runs_suite(line, "all")
