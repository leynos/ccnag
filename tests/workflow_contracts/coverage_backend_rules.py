"""Hold the coverage build's LLVM backend in what `make -n coverage` prints.

The development profile selects the Cranelift backend (`tools/dev-fast` and the
Cargo configuration), and Cranelift cannot instrument code for coverage. The
coverage recipe therefore sets `CARGO_PROFILE_DEV_CODEGEN_BACKEND=llvm` on the
command that runs `cargo llvm-cov`. A recipe that loses the assignment, or sets
another backend, would build an uninstrumented binary and report coverage that
means nothing, so the assignment is read from the printed command.
"""

from __future__ import annotations

import shlex
import typing as typ

VARIABLE: typ.Final[str] = "CARGO_PROFILE_DEV_CODEGEN_BACKEND"
BACKEND: typ.Final[str] = "llvm"
COVERAGE_TOOL: typ.Final[tuple[str, str]] = ("cargo", "llvm-cov")


def _commands(printed: str) -> list[list[str]]:
    """Split `make -n` output into commands, joining backslash continuations.

    Parameters
    ----------
    printed : str
        What `make -n` printed for a target.

    Returns
    -------
    list[list[str]]
        One word list per command; unparseable lines are skipped.

    """
    joined = printed.replace("\\\n", " ")
    commands: list[list[str]] = []
    for line in joined.splitlines():
        try:
            words = shlex.split(line, comments=False)
        except ValueError:
            continue
        if words:
            commands.append(words)
    return commands


def backend_violations(printed: str) -> list[str]:
    """List every way the coverage recipe fails to select the LLVM backend.

    Parameters
    ----------
    printed : str
        What `make -n coverage` printed.

    Returns
    -------
    list[str]
        One message per breach; empty when exactly the coverage command is found
        and its last assignment of `CARGO_PROFILE_DEV_CODEGEN_BACKEND` before `cargo` is `llvm`.

    """
    runs = [
        words
        for words in _commands(printed)
        if any(words[i : i + 2] == list(COVERAGE_TOOL) for i in range(len(words) - 1))
    ]
    if len(runs) != 1:
        return [f"expected one `cargo llvm-cov` command, found {len(runs)}"]
    words = runs[0]
    leading = words[: words.index("cargo")]
    values = [w.split("=", 1)[1] for w in leading if w.startswith(f"{VARIABLE}=")]
    # The shell applies the last assignment of a variable, so that is the one that counts.
    if not values or values[-1] != BACKEND:
        return [f"`cargo llvm-cov` assigns {VARIABLE}={values!r}, not {BACKEND!r}"]
    return []
