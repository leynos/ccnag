# Polonius borrow-checker policy

This project enables the Polonius alpha borrow-checking analysis
(`-Zpolonius=next`) on the dated nightly pinned in `rust-toolchain.toml`.
Polonius accepts borrow-returning control-flow patterns that non-lexical
lifetimes (NLL) reject, allowing internal APIs to model borrowing directly.

## Compiler contract

`.cargo/config.toml` enables Polonius for normal Cargo commands and
rust-analyzer. An inherited `RUSTFLAGS` value overrides that configuration, so
the Makefile and GitHub Actions workflows re-state `-Zpolonius=next` whenever
they set `RUSTFLAGS`. Release builds use the same pinned nightly and flag.

Source builds performed outside this repository, including registry installs,
do not inherit its toolchain or Cargo configuration. If this crate later ships
Polonius-only source through a registry, its installation instructions must
name both the pinned nightly and `RUSTFLAGS=-Zpolonius=next`, or direct users
to pre-built artefacts.

## Borrow-centric design

- Prefer lookup and get-or-create APIs that return references.
- Clone keys only on insertion, not on successful lookup.
- Build owned error context only in the failure branch where it escapes.
- Reserve ids and indexes for persistent or cross-boundary identity, not as
  substitutes for references.
- Remember that Polonius changes lifetime analysis, not aliasing: simultaneous
  mutable borrows, borrows across suspension points, lock-guard lifetimes, and
  thread boundaries remain real constraints.

## Audit tags

Use one of these greppable tags when a borrow-sensitive design needs its
classification preserved:

- `POLONIUS(case-3)` marks code verified to require the Polonius analysis.
- `POLONIUS-CANDIDATE(pattern)` marks an NLL workaround awaiting a verified
  borrow-centric rewrite.
- `POLONIUS-REFUSED(constraint)` records why an owned form remains necessary,
  such as `aliasing`, `suspension-point`, `lock-boundary`, or `id-is-data`.

Record verified sites below so later reviews start from evidence rather than
re-running the same analysis.

| Site     | Classification            | Verified nightly     | Notes                                             |
| -------- | ------------------------- | -------------------- | ------------------------------------------------- |
| None yet | Initial generated project | `nightly-2026-08-13` | Add rows as borrow-sensitive APIs are introduced. |

## Verification

For each borrow-sensitive change, first run the supported configuration:

```sh
make typecheck
make test
```

Then classify the changed form under plain NLL by overriding the checked-in
flag deliberately:

```sh
RUSTFLAGS= cargo +nightly-2026-08-13 check --all-targets --all-features
```

A no-flag failure establishes that the design genuinely requires Polonius; it
does not make the supported build invalid. Run the complete behavioural suite
under the normal Polonius-enabled configuration.
