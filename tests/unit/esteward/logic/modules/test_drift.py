"""M7 · drift: `[tool.edamlabs]` declares what the fleet says the project is."""

import pytest

from esteward.logic.modules.drift import DriftModule
from esteward.models.fleet import Fleet
from esteward.models.verdict import Verdict
from tests.unit.esteward.logic.conftest import FakeHost


@pytest.mark.parametrize(
    ("manifest", "expected"),
    [
        ('[tool.edamlabs]\nkind = "lib"\nfamily = "binding"\n', {"kind": Verdict.OK, "family": Verdict.OK}),
        ('[tool.edamlabs]\nkind = "lib"\n', {"kind": Verdict.OK, "family": Verdict.ACT}),
        (
            '[tool.edamlabs]\nkind = "service"\nfamily = "eager"\n',
            {"kind": Verdict.ESCALATE, "family": Verdict.ESCALATE},
        ),
        ('[project]\nname = "x"\n', {"kind": Verdict.ACT, "family": Verdict.ACT}),
        (None, {"kind": Verdict.ACT, "family": Verdict.ACT}),
    ],
    ids=["declared", "family-missing", "contradicted", "no-table", "no-manifest"],
)
async def test_run_identity(
    host: FakeHost, drift_module: DriftModule, fleet: Fleet, manifest: str | None, expected: dict[str, Verdict]
) -> None:
    host.files |= {("edamlabs/project", "pyproject.toml"): manifest} if manifest is not None else {}
    report = await drift_module.run(fleet)
    assert {f.check: f.verdict for f in report.findings} == expected
