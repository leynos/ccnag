# Architectural decision record (ADR) 001: Adopt the Rust build standard for development builds

## Status

Accepted on 8 October 2026. Development, test, lint and typecheck builds use
the parallel `rustc` frontend and, on Linux, the `mold` linker, with Cranelift
as the debug code generator. Coverage and release builds stay off the fast
flags, and coverage selects the LLVM backend explicitly.

## Date

2026-10-08.

## Context and problem statement

Edit-compile cycles are dominated by frontend time and by link time. The
estate's build standard (`rust-build-defaults`) addresses both with
`-Zthreads=8` and the `mold` linker on Linux. Cargo applies exactly one
`rustflags` source, and an assigned `RUSTFLAGS` replaces every configuration
source, so a recipe or workflow step that assigns `RUSTFLAGS` silently loses
the flags unless it restates them. Measurements and shipped artefacts also need
a baseline that the fast flags would disturb, and Cranelift cannot instrument
code for coverage.

## Decision drivers

- Faster local and CI development builds without changing what the code means.
- Coverage numbers that do not depend on the frontend flag, the linker or the
  backend.
- A release that ships from the platform linker.
- A flag lost through a recipe or workflow edit must fail a test, not pass
  quietly.

## Options considered

- Configure the flags only in `.cargo/config.toml`. This leaves every recipe
  and CI step that assigns `RUSTFLAGS` without them.
- Restate the flags in each recipe and step, held by contract tests. This is
  the option taken.
- Run coverage on the same backend as development. Cranelift does not emit the
  instrumentation `cargo llvm-cov` needs, so the build would report nothing
  useful.

## Decision outcome

`.cargo/config.toml` carries `-Zpolonius=next` and `-Zthreads=8` in every
`rustflags` source and adds `-C link-arg=-fuse-ld=mold` to the Linux table. The
Makefile composes the same flags into each development recipe, keeping the
caller's own `RUSTFLAGS`. The coverage recipe assigns its own flags, links with
`lld` and sets `CARGO_PROFILE_DEV_CODEGEN_BACKEND=llvm`. The release recipe
keeps the caller's flags and adds only the warning deny and the borrow-checker
flag, so it ships from the platform linker; a direct `cargo build --release`
takes the configuration's flags unless `RUSTFLAGS` is assigned.

Three contracts hold the decision. `tests/build_standard_contract.rs` reads the
Cargo configuration sources and the commands `make -n` prints for each target.
`tests/workflow_contracts/build_standard_test.py` reads the workflows as YAML
and requires every `setup-rust` step outside the release workflow to pass
`install-mold: 'true'` under `with:`.
`tests/workflow_contracts/coverage_backend_test.py` requires the coverage
command to assign the LLVM backend.

## Consequences

- Linux builds require `mold`, and its flag reaches the linker through `clang`,
  which `.cargo/config.toml` selects explicitly for `x86_64-unknown-linux-gnu`.
- A change to a recipe or workflow step that assigns `RUSTFLAGS` must restate
  the flags, and the contracts say which one fails when it does not.
- Re-measure the suite under Cranelift when real tests replace the template
  stub, and when the toolchain pin moves.
