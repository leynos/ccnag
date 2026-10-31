"""Contract test for the development build footprint rule.

The Concordat ``rust-dev-build-footprint`` rule needs the default development
profile to disable incremental compilation and debug information, and a dated
nightly pin to set the native Cargo metadata key for its date. This test holds
all three settings, so an edit cannot quietly re-enable either profile key or
swap in a raw rustc metadata flag, which broke build scripts.

Run via ``make test-workflow-contracts``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
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


# --- Effective Cargo behaviour -------------------------------------------------
#
# The checks above read files. These run the pinned Cargo on a one-file crate
# that carries this repository's own ``[profile.dev]`` table and Cargo
# configuration, and read the rustc command lines Cargo prints with ``-v``, so
# the settings are proved at the Cargo boundary and not only on the page.

FIXTURE_LIB: typ.Final[str] = "pub fn footprint() {}\n"
RUSTC_LINE: typ.Final[re.Pattern[str]] = re.compile(r"Running `.*--crate-name footprint .*`")
WRAPPER_VARIABLES: typ.Final[tuple[str, ...]] = (
    "RUSTC_WRAPPER",
    "RUSTC_WORKSPACE_WRAPPER",
    "CARGO_BUILD_RUSTC_WRAPPER",
    "CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER",
    "CARGO_INCREMENTAL",
    "CARGO_PROFILE_DEV_DEBUG",
    "CARGO_PROFILE_DEV_INCREMENTAL",
)


def _dev_profile_text() -> str:
    """Return the repository's ``[profile.dev]`` table text, header included."""
    manifest = (ROOT / "Cargo.toml").read_text("utf-8")
    match = re.search(r"^\[profile\.dev\]\n(?:(?!\[).*\n?)*", manifest, re.MULTILINE)
    assert match is not None, "Cargo.toml must carry a [profile.dev] table"
    return match.group(0)


def _compile_fixture(
    tmp_path: Path, extra_env: dict[str, str] | None = None
) -> str:
    """Build the fixture crate and return the rustc command line Cargo ran.

    The fixture holds the repository's Cargo configuration and ``[profile.dev]``
    table, and builds under the repository's pinned channel with every
    wrapper and profile override removed from the environment, so only the
    repository's own settings and the override under test apply.
    """
    channel = _load("rust-toolchain.toml")["toolchain"]["channel"]
    crate = tmp_path / "footprint"
    (crate / "src").mkdir(parents=True)
    (crate / ".cargo").mkdir()
    (crate / "Cargo.toml").write_text(
        '[package]\nname = "footprint"\nversion = "0.0.0"\nedition = "2024"\n\n'
        + _dev_profile_text(),
        "utf-8",
    )
    (crate / "src" / "lib.rs").write_text(FIXTURE_LIB, "utf-8")
    shutil.copy(ROOT / ".cargo" / "config.toml", crate / ".cargo" / "config.toml")
    env = {k: v for k, v in os.environ.items() if k not in WRAPPER_VARIABLES}
    env["CARGO_TARGET_DIR"] = str(tmp_path / "target")
    env.update(extra_env or {})
    result = subprocess.run(  # noqa: S603 - a fixed command
        ["cargo", f"+{channel}", "build", "--color", "never", "--offline", "-v"],
        cwd=crate,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"cargo build failed:\n{result.stderr}"
    lines = RUSTC_LINE.findall(result.stderr)
    assert lines, f"no rustc command line in Cargo's output:\n{result.stderr}"
    return lines[0]


def test_cargo_builds_by_default_without_incremental_state_or_debug_info(
    tmp_path: Path,
) -> None:
    """A default dev build passes no ``debuginfo`` or ``incremental`` and no embedding."""
    command = _compile_fixture(tmp_path)
    assert "-C debuginfo" not in command, f"debug info must be off: {command}"
    assert "-C incremental" not in command, f"incremental must be off: {command}"
    assert "-Z embed-metadata=no" in command, (
        f"Cargo must coordinate metadata natively: {command}"
    )


def test_the_documented_debug_override_turns_debug_info_back_on(
    tmp_path: Path,
) -> None:
    """``CARGO_PROFILE_DEV_DEBUG=true`` restores debug information."""
    command = _compile_fixture(tmp_path, {"CARGO_PROFILE_DEV_DEBUG": "true"})
    assert "-C debuginfo=2" in command, f"the override must restore debug info: {command}"


def test_the_documented_incremental_override_turns_incremental_back_on(
    tmp_path: Path,
) -> None:
    """``CARGO_INCREMENTAL=1`` restores incremental compilation."""
    command = _compile_fixture(tmp_path, {"CARGO_INCREMENTAL": "1"})
    assert "-C incremental=" in command, f"the override must restore incremental: {command}"
