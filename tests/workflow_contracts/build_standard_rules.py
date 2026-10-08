"""Hold the build standard's mold install in the parsed workflows.

`.cargo/config.toml` links with mold on Linux, so every workflow job that
builds under the standard installs it through `setup-rust`'s `install-mold`
input. The release workflow ships from the platform linker and is left out.

The Rust contract (`tests/build_standard_contract.rs`) reads the same steps as
text. This module reads them as YAML, so a step is judged by its own mapping:
the action's identity is checked whole, the input must sit under `with:`, and a
key of that name beside `uses:` does not count.
"""

from __future__ import annotations

import re
import typing as typ

from codescene_environment_rules import Workflow
from sccache_lane_rules import RELEASE, SETUP_RUST, setup_steps

#: The action coordinate in full: the shared action's path and a commit SHA.
#: Dependabot owns the revision, so any full SHA is accepted.
ACTION: typ.Final[re.Pattern[str]] = re.compile(
    re.escape(SETUP_RUST) + r"[0-9a-f]{40}"
)
INPUT: typ.Final[str] = "install-mold"
ENABLED: typ.Final[frozenset[object]] = frozenset({"true", True})


def mold_violations(workflows: dict[str, Workflow]) -> list[str]:
    """List every way a building workflow fails to install mold.

    Parameters
    ----------
    workflows : dict[str, Workflow]
        The parsed workflows by file name.

    Returns
    -------
    list[str]
        One message per breach; empty when every `setup-rust` step outside the
        release workflow names the action whole and passes `install-mold: 'true'`
        under `with:`, and at least one such step exists.

    """
    problems: list[str] = []
    seen = 0
    for name, workflow in sorted(workflows.items()):
        if name == RELEASE:
            continue
        for step in setup_steps(workflow):
            seen += 1
            where = f"{name}: step {step.get('name', '<unnamed>')!r}"
            if not ACTION.fullmatch(str(step.get("uses", ""))):
                problems.append(f"{where} does not name the action whole at a commit SHA")
            if INPUT in step:
                problems.append(f"{where} sets `{INPUT}` beside `uses:`, not under `with:`")
            if (step.get("with") or {}).get(INPUT) not in ENABLED:
                problems.append(f"{where} does not pass `{INPUT}: 'true'` under `with:`")
    if seen == 0:
        problems.append("no `setup-rust` step was found, so the check proves nothing")
    return problems
