"""Contract test for the development build footprint rule.

The Concordat ``rust-dev-build-footprint`` rule needs the default development
profile to disable incremental compilation and debug information, and a dated
nightly pin to set the native Cargo metadata key for its date. This test holds
all three settings, so an edit cannot quietly re-enable either profile key or
swap in a raw rustc metadata flag, which broke build scripts.

Run via ``make test-workflow-contracts``.
"""

from __future__ import annotations

import re
import tomllib
import typing as typ
from pathlib import Path

import pytest

ROOT: typ.Final[Path] = Path(__file__).resolve().parents[2]
NATIVE_KEY_FROM: typ.Final[str] = "2026-07-31"
DATED_NIGHTLY: typ.Final[re.Pattern[str]] = re.compile(r"^nightly-(\d{4}-\d{2}-\d{2})$")


def _load(relative: str) -> dict[str, typ.Any]:
    """Return a parsed TOML file of the repository."""
    return tomllib.loads((ROOT / relative).read_text("utf-8"))


def _is_zero_debug(debug: object) -> bool:
    """Accept the exact integer ``0`` or the boolean ``false``.

    Python equality would also accept ``0.0``, which Cargo rejects.
    """
    is_zero_integer = (
        isinstance(debug, int) and not isinstance(debug, bool) and debug == 0
    )
    return debug is False or is_zero_integer


def test_development_profile_keeps_the_build_footprint_settings() -> None:
    """The default dev profile sets ``incremental = false`` and ``debug = 0``."""
    dev = _load("Cargo.toml").get("profile", {}).get("dev", {})
    assert dev.get("incremental") is False, "profile.dev must set incremental = false"
    assert _is_zero_debug(dev.get("debug")), "profile.dev must set debug = 0 or false"


def test_cargo_config_disables_metadata_embedding_natively() -> None:
    """``.cargo/config.toml`` sets the native ``[unstable] embed-metadata = false``."""
    config = _load(".cargo/config.toml")
    assert config.get("unstable", {}).get("embed-metadata") is False, (
        ".cargo/config.toml must set [unstable] embed-metadata = false"
    )
    assert "no-embed-metadata" not in config.get("unstable", {}), (
        "the older no-embed-metadata spelling is wrong for a pin from 2026-07-31"
    )


def test_no_raw_rustc_metadata_flag_appears_in_any_rustflags_source() -> None:
    """Raw ``-Zembed-metadata`` style rustflags are refused."""
    config = _load(".cargo/config.toml")
    sources = [
        config.get("build", {}).get("rustflags", []),
        *(table.get("rustflags", []) for table in config.get("target", {}).values()),
    ]
    flags = [str(flag) for source in sources for flag in source]
    assert not any("embed-metadata" in flag for flag in flags), (
        f"no raw embed-metadata flag may appear in rustflags: {flags}"
    )


def test_the_pin_is_a_dated_nightly_that_accepts_the_native_key() -> None:
    """The native key is only right for a dated nightly from 2026-07-31."""
    channel = _load("rust-toolchain.toml")["toolchain"]["channel"]
    match = DATED_NIGHTLY.match(channel)
    if match is None:
        pytest.fail(f"expected a dated nightly pin, found {channel!r}")
    assert match.group(1) >= NATIVE_KEY_FROM, (
        f"{channel} predates {NATIVE_KEY_FROM}: use the no-embed-metadata key"
    )
