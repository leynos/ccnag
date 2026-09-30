# Developer Guide

This guide explains the contributor workflow for the generated ccnag project.

## Local Workflow

Use `make all` as the public entrypoint for formatting, linting, and tests.
`make lint` runs rustdoc, Clippy, and Whitaker. `make test` prefers
`cargo nextest run` and falls back to `cargo test` when cargo-nextest is not
available. `make check-fmt` verifies Rust formatting with
`cargo fmt --all -- --check`, and `make fmt` formats Rust sources with nightly
`rustfmt` and Markdown with `mdformat`. `make typecheck` type-checks without
building via `cargo check`. `make audit` derives the Rust workspace root with
`cargo metadata`, logs workspace member manifests, and runs `cargo audit` once
from the workspace root. PR CI skips `make audit` and the audit-only setup when
`github.actor` is `dependabot[bot]`; that keeps whole-lockfile advisories from
blocking unrelated Dependabot PRs while human PRs retain the audit gate. The
compensating control is `.github/workflows/audit.yml`, which runs weekly and
can also be triggered manually. `make coverage` uses `cargo llvm-cov` with
`lld`.

The test suite runs once per pull request, in `ci.yml`'s coverage step. That
step runs the same tests `make test` runs except the doctests, which
`build-test` runs in a step of its own with
`cargo test --doc --workspace --all-features`. The repository used to carry an
`act-validation.yml` workflow that ran `make test WITH_ACT=1`, but nothing reads
`WITH_ACT` and no test is gated on Act, so that workflow ran the whole suite a
second time and was removed. The crate declares no features, so `make test`'s
`--all-features` selects the same tests as the coverage run's default.

`tests/workflow_contracts/suite_runs_once_test.py` holds the split. It reads
commands through `tests/workflow_contracts/suite_commands.py`, which splits a
command the way the shell does and decides whether it runs the suite. That
module belongs to the suite-once contract alone: no other test calls it, and no
production code depends on it. Callers pass the Makefile's default goal in, so
a bare `make` counts as a suite run only where that goal runs the suite. Extend
the reader by adding a spelling case to the contract, and prove it with a
mutation of `ci.yml` that the previous reader missed.

A scheduled `.github/workflows/mutation-testing.yml` workflow also runs
`cargo-mutants` via the shared reusable workflow, daily and on manual dispatch.
It is informational and does not gate pull requests. Dependabot keeps its
pinned reusable-workflow SHA current. See the user guide's "Scheduled Mutation
Testing" section for behaviour, and promote surviving mutants into new tests.

## Tooling

### Polonius borrow checker

This project compiles with the Polonius alpha analysis (`-Zpolonius=next`) on
the dated nightly pinned in `rust-toolchain.toml`. `.cargo/config.toml`
supplies the flag by default; Makefile recipes and workflows that set
`RUSTFLAGS` must re-state it because the environment value overrides Cargo
configuration. See [the Polonius policy](polonius.md) for the borrow-centric
API and audit-tag conventions.

Generated CI and coverage workflows, plus the release workflow rendered for
applications, pass this base flag through the shared `setup-rust` action's
`rustflags` input. Library renders do not include `release.yml`. The pinned
revision must expose that input, and coverage overrides must repeat the
selected base flag alongside their `lld` linker flag. Contract tests should
assert these inputs and combined flags.

Development builds use Cranelift for debug code generation. On Linux targets,
`.cargo/config.toml` configures clang to link with `mold` so debug builds link
quickly. Coverage generation uses `lld` because LLVM coverage tooling expects
LLVM-compatible linker behaviour.

Install `clang`, `lld`, `mold`, `python3`, and `cargo-audit` before running the
full generated workflow locally on Linux.

### Release builds

`release.yml` runs on a `v*.*.*` tag push and on `workflow_dispatch`, and
builds six targets in one matrix, each leg with a `builder`.

- **Native macOS.** `x86_64-apple-darwin` builds on `macos-15-intel` and
  `aarch64-apple-darwin` on `macos-latest`, with
  `cargo +nightly-2026-08-13 build --release --target <target>`. `cross` has no
  Docker image for Apple targets; on a Linux runner it falls back to host
  cargo, which lacks the target and stops with E0463, so those legs could never
  build there.
- **Cross for the rest.** The Linux (`x86_64`, `aarch64`), Windows GNU and
  FreeBSD legs run `cross build --release --target <target>` on
  `ubuntu-latest`, taking the nightly from `rust-toolchain.toml`: cross
  composes a malformed toolchain name (`nightly-2026-08-13-2026-08-13-<host>`)
  from an explicit dated `+toolchain`.
- **Linker for the x86_64 Linux leg.** `.cargo/config.toml` names `clang` as
  that triple's linker for the development build (with mold). The `cross` image
  has gcc and no clang, so the cross step sets
  `CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=cc`. An environment value beats
  the configuration file and `cross` forwards `CARGO_*` variables into its
  container. The development configuration is untouched.
- **No cancellation.** `fail-fast` is off, so one failing leg cannot hide
  whether the others build.
- **Dry run.** A `workflow_dispatch` builds every leg and uploads the
  artefacts, then stops: the `release` job runs only for a tag push, or for a
  dispatch on a tag ref that sets `dry-run` to `false`. A branch dispatch
  therefore never publishes. Run the dispatch on a branch before tagging; it is
  the proof that every leg builds.

`tests/workflow_contracts/release_workflow_test.py` holds these clauses: each
is proved by a mutation of a copy of the real workflow that the contract must
refuse.

### Compiler cache (sccache)

The shared `setup-rust` action gives sccache a local-disk directory under
`runner.temp` on a GitHub-hosted runner. The directory is restored with
`actions/cache` on every event and saved only on a push to `main`, so a pull
request reads the cache and never writes one.

- **One shared lane.** `ci.yml`'s `build-test` and `coverage-main.yml`'s
  `coverage-upload` both set `sccache-cache-discriminator: coverage`. The
  action's default discriminator is the job ID, which would give the two jobs
  different lanes and leave the pull-request lane without a writer. Only
  `coverage-upload` runs on a push to `main`, so it is the writer and
  `build-test` is the reader. Keep the two values equal.
- **What it warms.** The lane holds the artefacts of the coverage build, so the
  coverage step of `build-test` restores from it. The lint step compiles a
  different graph and gains almost nothing from it; measured on frankie, lint
  hit 2.5 % and the coverage step hit 100 %.
- **`expect-cache: any`.** A GitHub-hosted job accepts whichever cache backend
  the runner offers, so the input is set explicitly.
- **`release.yml` disables it.** The release job builds with `cross` inside a
  container that receives neither `RUSTC_WRAPPER` nor `SCCACHE_PATH`, so
  sccache is switched off there with `use-sccache: 'false'`. The contract
  `tests/workflow_contracts/sccache_lane_test.py` holds all three clauses
  (`expect-cache`, the shared discriminator, and the release switch) by action
  name and inputs, never by a revision.

## Spelling policy

Markdown uses en-GB-oxendict spelling enforced by `make spelling`, which runs
the `typos-config-builder` gate pinned in the `Makefile`. The gate regenerates
`typos.toml` from the live estate-wide shared dictionary and the narrow
repository overlay in `typos.local.toml` on every run, then checks maintained
Markdown prose. The tracked `typos.toml` is a build artefact: it is never
drift-checked in CI, so a shared-dictionary update lands on the next run
without a follow-up commit here. Add narrow repository exceptions to
`typos.local.toml` and re-run `make spelling`.

### Security audit ignores

Security audit jobs may set `CARGO_AUDIT_IGNORES` for narrowly scoped RustSec
advisories that affect unused or tooling-only dependency paths. Keep each
ignore tied to a documented runtime impact analysis, and remove it when the
affected dependency leaves the graph or the project starts using the advised
runtime path.

## Workflow pins and Dependabot

Dependabot owns the upgrade of GitHub Actions and reusable workflows, including
calls into `leynos/shared-actions`. Contract tests that assert a caller's exact
commit SHA create a lockstep dependency: every time Dependabot opens a bump PR,
the test fails until a human edits the pinned constant to match. That defeats
the purpose of automated dependency updates and turns a routine bump into a
manual chore.

The narrow `RUSTFLAGS_PASSTHROUGH_REVISION` exception applies only while no
independent capability probe can establish that the shared `setup-rust` action
accepts the required `rustflags` input. In that case, assert the first revision
that provides the capability and document this boundary beside the test. Remove
the literal revision assertion once an independent capability probe is
available.

Contract tests may still verify the *shape* of a reusable-workflow caller. They
must not verify the specific SHA value.

- Do assert the workflow references the correct reusable workflow path.
- Do assert the ref is pinned to a full 40-character commit SHA, not a
  mutable branch such as `main` or `rolling`.
- Do assert the expected `on:` triggers, least-privilege `permissions:`, and
  the inputs the caller relies on.
- Do not hard-code the current SHA value as an expected string. Match it with
  a pattern instead.
- Do not fail a test purely because Dependabot bumped the pinned SHA.

```python
import re

SHA_RE = re.compile(r"^[0-9a-f]{40}$")

def test_uses_pinned_full_sha(caller_step):
    ref = caller_step["uses"].split("@")[-1]
    assert SHA_RE.match(ref), f"expected a 40-hex commit SHA, got {ref!r}"
```

If a workflow's behaviour genuinely depends on a feature only present from a
particular commit onwards, express that as a comment or a changelog note, not
as a test assertion on the SHA string. The sole exception is the
`RUSTFLAGS_PASSTHROUGH_REVISION` boundary above: until an independent probe can
confirm that `setup-rust` supports `rustflags`, document and assert the first
capable revision. Remove that literal revision assertion once the probe exists.

## Workflow contracts

`make test-workflow-contracts` runs the tests under
`tests/workflow_contracts/`, which parse the GitHub workflow files and assert
the mechanisms they must contain (for example, that no workflow runs the suite
outside the coverage step and that `build-test` runs the doctests). The target
needs only `uv` on `PATH`, because it runs:

```sh
uv run --no-project --with 'pytest>=8' --with 'pyyaml>=6' pytest tests/workflow_contracts -q
```

No project environment or extra install is required. Run it after editing
anything under `.github/workflows/`; CI runs it in `build-test` after the
spelling check, and the contract fails the build if a workflow loses a
mechanism it depends on.
