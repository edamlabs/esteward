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


@pytest.mark.parametrize(
    ("files", "expected", "where"),
    [
        ({"Cargo.toml": '[package.metadata.edamlabs]\nkind = "lib"\nfamily = "binding"\n'}, Verdict.OK, "Cargo.toml"),
        ({"Cargo.toml": '[workspace.metadata.edamlabs]\nkind = "lib"\nfamily = "binding"\n'}, Verdict.OK, "Cargo.toml"),
        (
            {
                "pyproject.toml": '[project]\nname = "x"\n',
                "Cargo.toml": '[package.metadata.edamlabs]\nkind = "lib"\nfamily = "binding"\n',
            },
            Verdict.OK,
            "Cargo.toml",
        ),
        ({"Cargo.toml": '[package]\nname = "x"\n'}, Verdict.ACT, "Cargo.toml [package.metadata.edamlabs]"),
    ],
    ids=["cargo-package", "cargo-workspace", "pyproject-without-table-yields", "cargo-without-table"],
)
async def test_run_identity_cargo(
    host: FakeHost, drift_module: DriftModule, fleet: Fleet, files: dict[str, str], expected: Verdict, where: str
) -> None:
    host.files |= {("edamlabs/project", name): text for name, text in files.items()}
    report = await drift_module.run(fleet)
    assert {f.verdict for f in report.findings} == {expected}
    assert all(where in f.detail for f in report.findings if f.verdict is Verdict.ACT)
