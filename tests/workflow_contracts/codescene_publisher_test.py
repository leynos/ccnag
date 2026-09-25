"""Contract-test where the CodeScene token may appear in the publisher.

The upload is ``upload-codescene-coverage``, a composite action. A composite
action's nested steps inherit the calling step's environment, so a token bound
in the upload step's ``env``, or the job's, or the workflow's, reaches every
step inside the action. ``coverage-main.yml`` therefore keeps the token out of
every ``env``. A check step publishes only whether the token exists, the
upload's guard reads that output beside the main-ref guard, and the upload
takes the token directly as an input.

The positive half matters as much as the prohibition. Deleting the token keeps
every ``env`` clean while the upload's guard goes false and publishing silently
stops, so the token's sites are held to exactly the check's command and the
upload's input.
"""

from __future__ import annotations

import pathlib
import typing as typ

import yaml

if typ.TYPE_CHECKING:
    import collections.abc as cabc

type Mapping = dict[str, typ.Any]

PUBLISHER_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / ".github/workflows/coverage-main.yml"
)
JOB = "coverage-upload"
CHECK_ID = "codescene_token"
#: GitHub evaluates the expression before it sends the command to the runner,
#: so the check's shell receives only ``true`` or ``false``.
CHECK_COMMAND = (
    'echo "available=${{ secrets.CS_ACCESS_TOKEN != \'\' }}" >> "$GITHUB_OUTPUT"'
)
AVAILABLE_CONJUNCT = f"steps.{CHECK_ID}.outputs.available == 'true'"
MAIN_REF_CONJUNCT = "github.ref == 'refs/heads/main'"
UPLOAD_CREDENTIAL_INPUT = "${{ secrets.CS_ACCESS_TOKEN }}"
#: Expression contexts are case-insensitive, so every search folds case.
CREDENTIAL_NAME = "cs_access_token"


def _publisher() -> Mapping:
    """Return the decoded publisher workflow."""
    workflow = yaml.safe_load(PUBLISHER_PATH.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict), "coverage-main.yml must contain a mapping"
    return workflow


def _steps(workflow: Mapping) -> list[Mapping]:
    """Return the publisher job's mapping-shaped steps, in order."""
    steps = workflow["jobs"][JOB]["steps"]
    return [step for step in steps if isinstance(step, dict)]


def _is_upload(step: Mapping) -> bool:
    """Report whether a step calls the CodeScene uploader."""
    return "upload-codescene-coverage" in str(step.get("uses", ""))


def _located_strings(value: object, path: str) -> cabc.Iterator[tuple[str, str]]:
    """Yield every string in a parsed YAML value with the path reaching it.

    A mapping key is reported at the path of the entry it names, so an ``env``
    entry named after the token is found there.

    Yields
    ------
    tuple[str, str]
        The path and the string found there.

    Examples
    --------
    >>> list(_located_strings({"env": {"T": "x"}}, "job"))
    [('job.env', 'env'), ('job.env.T', 'T'), ('job.env.T', 'x')]
    """
    match value:
        case str():
            yield path, value
        case dict():
            for key, item in value.items():
                child = f"{path}.{key}" if path else str(key)
                if isinstance(key, str):
                    yield child, key
                yield from _located_strings(item, child)
        case list():
            for index, item in enumerate(value):
                yield from _located_strings(item, f"{path}[{index}]")
        case _:
            return


def test_the_check_step_publishes_availability_and_nothing_else() -> None:
    """Run one exact command, unconditionally, with no env, before the upload.

    A condition on the check would leave its output unset whenever it was
    false, so the upload would skip forever, and an ``env`` would put the
    token back into an environment.
    """
    steps = _steps(_publisher())
    checks = [step for step in steps if step.get("id") == CHECK_ID]
    uploads = [step for step in steps if _is_upload(step)]
    assert len(checks) == 1, f"expected one {CHECK_ID!r} step, found {len(checks)}"
    assert len(uploads) == 1, f"expected one upload, found {len(uploads)}"
    check = checks[0]
    assert str(check.get("run", "")).strip() == CHECK_COMMAND, check.get("run")
    assert "if" not in check, "the check must run unconditionally"
    assert "env" not in check, "the check must declare no env"
    assert steps.index(check) < steps.index(uploads[0]), (
        "the check must run before the upload that reads its output"
    )


def test_the_upload_reads_the_check_and_the_ref() -> None:
    """Guard the upload on the check's output and on main, with no ``||``."""
    (upload,) = [step for step in _steps(_publisher()) if _is_upload(step)]
    condition = str(upload.get("if", ""))
    assert "||" not in condition, f"no disjunction may widen {condition!r}"
    conjuncts = [part.strip() for part in condition.split("&&")]
    for required in (AVAILABLE_CONJUNCT, MAIN_REF_CONJUNCT):
        assert required in conjuncts, f"{required!r} missing from {condition!r}"


def test_the_upload_takes_the_token_as_its_input() -> None:
    """Pass the secret as the action's input, not through an environment."""
    (upload,) = [step for step in _steps(_publisher()) if _is_upload(step)]
    access_token = (upload.get("with") or {}).get("access-token")
    assert access_token == UPLOAD_CREDENTIAL_INPUT, access_token


def test_the_token_appears_exactly_where_it_is_used() -> None:
    """Name the token at the check's command and the upload's input only.

    Compared by location, so the right expression in the wrong place is
    refused, and an ``env`` naming the token at any scope fails here.
    """
    workflow = _publisher()
    steps = workflow["jobs"][JOB]["steps"]
    check_at = next(i for i, step in enumerate(steps) if step.get("id") == CHECK_ID)
    upload_at = next(i for i, step in enumerate(steps) if _is_upload(step))
    at = f"jobs.{JOB}.steps"
    expected = sorted([f"{at}[{check_at}].run", f"{at}[{upload_at}].with.access-token"])
    found = sorted({
        path
        for path, text in _located_strings(workflow, "")
        if CREDENTIAL_NAME in text.casefold()
    })
    assert found == expected, f"expected the token only at {expected}, found {found}"
