"""Prove the coverage backend clause holds, and that it bites on each defect."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from coverage_backend_rules import backend_violations

ROOT = Path(__file__).resolve().parents[2]

COMPLIANT = (
    'echo "coverage linker flags: -fuse-ld=lld"\n'
    "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=clang \\\n"
    "\tCARGO_PROFILE_DEV_CODEGEN_BACKEND=llvm \\\n"
    '\tRUSTFLAGS="-D warnings" \\\n'
    "\tcargo llvm-cov --lcov --output-path lcov.info\n"
)


def test_the_real_coverage_recipe_selects_llvm(gnu_make: str) -> None:
    """`make -n coverage` assigns the LLVM backend on the instrumented build."""
    printed = subprocess.run(  # noqa: S603 - a fixed command
        [gnu_make, "-n", "-B", "coverage"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert backend_violations(printed) == []


def test_a_compliant_recipe_is_accepted() -> None:
    """The recipe as written passes, and so does a harmless repeat."""
    assert backend_violations(COMPLIANT) == []
    repeated = COMPLIANT.replace("\tRUSTFLAGS", "\tCARGO_PROFILE_DEV_CODEGEN_BACKEND=llvm \\\n\tRUSTFLAGS")
    assert backend_violations(repeated) == []


@pytest.mark.parametrize(
    ("label", "printed"),
    [
        ("the assignment is gone", COMPLIANT.replace("\tCARGO_PROFILE_DEV_CODEGEN_BACKEND=llvm \\\n", "")),
        ("another backend is named", COMPLIANT.replace("=llvm", "=cranelift")),
        ("an empty value is assigned", COMPLIANT.replace("=llvm", "=")),
        ("a later assignment overrides it", COMPLIANT.replace("\tRUSTFLAGS", "\tCARGO_PROFILE_DEV_CODEGEN_BACKEND=cranelift \\\n\tRUSTFLAGS")),
        ("the assignment sits on another command", 'CARGO_PROFILE_DEV_CODEGEN_BACKEND=llvm echo hi\ncargo llvm-cov --lcov\n'),
        ("no coverage command is printed", 'echo "coverage"\n'),
        ("two coverage commands are printed", COMPLIANT + COMPLIANT),
    ],
)
def test_a_defective_recipe_is_refused(label: str, printed: str) -> None:
    """Each way of losing or muddling the assignment draws a complaint."""
    assert backend_violations(printed), label
