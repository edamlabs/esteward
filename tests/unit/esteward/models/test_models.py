"""Verdict ladder, report aggregate, fleet entry loading."""

from datetime import datetime
from pathlib import Path

import msgspec
import pytest

from esteward.models.fleet import Fleet, KindFleet, ModuleFleet
from esteward.models.report import FindingReport, Report
from esteward.models.verdict import Verdict


async def test_verdict_rank() -> None:
    assert [v.rank for v in (Verdict.OK, Verdict.WATCH, Verdict.ACT, Verdict.ESCALATE)] == [0, 1, 2, 3]


@pytest.mark.parametrize(
    ("verdicts", "expected"),
    [((), Verdict.OK), ((Verdict.WATCH, Verdict.ACT, Verdict.OK), Verdict.ACT)],
    ids=["empty", "most-severe"],
)
async def test_report_verdict(now: datetime, verdicts: tuple[Verdict, ...], expected: Verdict) -> None:
    findings = tuple(
        FindingReport(key=str(i), module="m", subject="s", check="c", verdict=v, detail="d")
        for i, v in enumerate(verdicts)
    )
    assert Report(repo="r", module="m", generated=now, findings=findings).verdict is expected


async def test_fleet_load(tmp_path: Path) -> None:
    entry = tmp_path / "x.toml"
    entry.write_text(
        'repo = "edamlabs/x"\nkind = "service"\nfamily = "eager"\nmodules = ["security"]\n', encoding="utf-8"
    )
    fleet = Fleet.load(entry)
    assert (fleet.kind, fleet.modules, fleet.deps.watch, fleet.security.paths) == (
        KindFleet.SERVICE,
        (ModuleFleet.SECURITY,),
        (),
        (".github/workflows",),
    )


async def test_fleet_load_invalid(tmp_path: Path) -> None:
    entry = tmp_path / "x.toml"
    entry.write_text('repo = "edamlabs/x"\nkind = "desktop"\nfamily = "eager"\nmodules = []\n', encoding="utf-8")
    with pytest.raises(msgspec.ValidationError):
        Fleet.load(entry)


FLEET_ENTRIES = tuple(sorted(Path("fleet").glob("*.toml")))


@pytest.mark.parametrize("entry", FLEET_ENTRIES, ids=[path.stem for path in FLEET_ENTRIES])
async def test_fleet_entries_valid(entry: Path) -> None:
    assert Fleet.load(entry).repo == f"edamlabs/{entry.stem}"
