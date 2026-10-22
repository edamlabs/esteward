"""Settings, logging and the run's resources."""

import pytest
import structlog

from esteward.adapters.github import GithubAdapter
from esteward.core.lifespan import lifespan
from esteward.core.logger import setup_logger
from esteward.core.settings import EnvSettings, Settings


@pytest.mark.parametrize(
    "variable", ["ESTEWARD_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"], ids=["own", "gh", "actions"]
)
async def test_settings_token(monkeypatch: pytest.MonkeyPatch, variable: str) -> None:
    monkeypatch.setenv(variable, "t0ken")
    token = Settings().github_token
    assert token is not None
    assert token.get_secret_value() == "t0ken"


@pytest.mark.parametrize("env", list(EnvSettings), ids=[str(e) for e in EnvSettings])
async def test_setup_logger(env: EnvSettings, capsys: pytest.CaptureFixture[str]) -> None:
    setup_logger(env, "info")
    structlog.get_logger().info("probe_event", answer=42)
    structlog.get_logger().debug("filtered_event")
    err = capsys.readouterr().err
    assert "probe_event" in err
    assert "filtered_event" not in err
    structlog.reset_defaults()


@pytest.mark.parametrize("token", [None, "t0ken"], ids=["anonymous", "authenticated"])
async def test_lifespan(token: str | None) -> None:
    async with lifespan(Settings(github_token=token)) as runtime:
        assert isinstance(runtime.github, GithubAdapter)
        assert set(runtime.registries) == {"pypi.org", "crates.io"}
