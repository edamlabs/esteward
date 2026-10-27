"""M2 · upstream: the declared engines of a binding against their newest release."""

from collections.abc import Callable
from datetime import datetime

import pytest
from msgspec.structs import replace as restruct

from esteward.logic.modules.upstream import UpstreamModule
from esteward.models.fleet import EngineFleet, Fleet, UpstreamFleet
from esteward.models.signal import PackageSignal
from esteward.models.verdict import Verdict
from tests.unit.esteward.logic.conftest import FakeHost, FakeRegistry

ENGINE = EngineFleet(name="dep", registry="https://pypi.org/project/dep/", parity="1.0")
REPO = "edamlabs/project"


@pytest.fixture
def binding(fleet: Fleet) -> Fleet:
    """The fleet entry of a binding that mirrors one engine."""
    return restruct(fleet, upstream=UpstreamFleet(engines=(ENGINE,)))


@pytest.fixture
def upstream_module(host: FakeHost, registry: FakeRegistry, now: datetime) -> UpstreamModule:
    return UpstreamModule(host, {"pypi.org": registry}, now)


async def test_run_parity_current(
    upstream_module: UpstreamModule,
    binding: Fleet,
    registry: FakeRegistry,
    engine_signal: Callable[[str], PackageSignal],
) -> None:
    registry.packages["dep"] = engine_signal("1.0")
    (finding,) = (await upstream_module.run(binding)).findings
    assert (finding.key, finding.subject, finding.check, finding.verdict) == (
        "upstream:dep:parity",
        "dep",
        "parity",
        Verdict.OK,
    )
    assert finding.detail == "parity 1.0 is the engine's newest release"


@pytest.mark.parametrize(
    ("agent", "verdict"),
    [(True, Verdict.WATCH), (False, Verdict.ESCALATE)],
    ids=["sync-flow-owns-it", "no-agent-human"],
)
async def test_run_engine_ahead(
    upstream_module: UpstreamModule,
    binding: Fleet,
    host: FakeHost,
    registry: FakeRegistry,
    engine_signal: Callable[[str], PackageSignal],
    agent: bool,
    verdict: Verdict,
) -> None:
    registry.packages["dep"] = engine_signal("1.1")
    match agent:
        case True:
            host.files[REPO, ".github/workflows/sync.yml"] = "name: sync\n"
        case _:
            pass
    (finding,) = (await upstream_module.run(binding)).findings
    assert finding.verdict is verdict
    assert finding.detail.startswith("the engine released 1.1 beyond parity 1.0: ")


async def test_run_parity_ahead_of_engine(
    upstream_module: UpstreamModule,
    binding: Fleet,
    registry: FakeRegistry,
    engine_signal: Callable[[str], PackageSignal],
) -> None:
    registry.packages["dep"] = engine_signal("0.9")
    (finding,) = (await upstream_module.run(binding)).findings
    assert finding.verdict is Verdict.ESCALATE
    assert finding.detail == "parity 1.0 is ahead of the engine's newest 0.9: the declaration is wrong"


async def test_run_unorderable(
    upstream_module: UpstreamModule,
    binding: Fleet,
    registry: FakeRegistry,
    engine_signal: Callable[[str], PackageSignal],
) -> None:
    registry.packages["dep"] = engine_signal("calendar-2026")
    (finding,) = (await upstream_module.run(binding)).findings
    assert finding.verdict is Verdict.WATCH
    assert finding.detail == "cannot order the engine's newest calendar-2026 against parity 1.0"


async def test_run_vanished(upstream_module: UpstreamModule, binding: Fleet, registry: FakeRegistry) -> None:
    (finding,) = (await upstream_module.run(binding)).findings
    assert finding.verdict is Verdict.ESCALATE
    assert finding.detail == "https://pypi.org/project/dep/ not found: the engine's registry page is gone"
