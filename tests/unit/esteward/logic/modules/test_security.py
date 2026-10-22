"""M6 · security: pinned action commits must exist."""

import pytest
from msgspec.structs import replace as restruct

from esteward.logic.modules.security import SecurityModule
from esteward.models.fleet import Fleet, SecurityFleet
from esteward.models.verdict import Verdict
from tests.unit.esteward.logic.conftest import FakeHost

REAL = "a" * 40
PHANTOM = "b" * 40
WORKFLOW = f"""
jobs:
  build:
    steps:
      - uses: actions/checkout@{REAL}  # v6
      - uses: 'owner/tool/sub/path@{PHANTOM}'
      - uses: actions/checkout@{REAL}
      - uses: ./local-action
      - uses: owner/unpinned@v2
"""


@pytest.mark.parametrize(
    ("path", "found"),
    [(".github/workflows/ci.yml", True), ("infra/jobs/ci.yaml", False), (".github/workflows/notes.md", False)],
    ids=["workflow", "outside-paths", "not-yaml"],
)
async def test_run_pins(host: FakeHost, security_module: SecurityModule, fleet: Fleet, path: str, found: bool) -> None:
    host.files["edamlabs/project", path] = WORKFLOW
    host.commits.add(("actions/checkout", REAL))
    report = await security_module.run(fleet)
    expected = [("actions/checkout", Verdict.OK), ("owner/tool", Verdict.ESCALATE)] if found else []
    assert sorted((f.subject, f.verdict) for f in report.findings) == expected


async def test_run_configured_paths(host: FakeHost, security_module: SecurityModule, fleet: Fleet) -> None:
    host.files["edamlabs/project", "infra/jobs/release/wheels.yml"] = WORKFLOW
    widened = restruct(fleet, security=SecurityFleet(paths=(".github/workflows", "infra/jobs")))
    report = await security_module.run(widened)
    assert report.verdict is Verdict.ESCALATE
    assert {f.key for f in report.findings} == {
        f"security:pin:actions/checkout@{REAL}",
        f"security:pin:owner/tool@{PHANTOM}",
    }
