# esteward

The self-maintenance engine of EDamLabs projects. It watches every project in `fleet/`, decides
deterministically, and acts on its own: one pinned **status issue** per repository, one **issue per
incident** that closes itself when the incident clears. No pull request waits for a human.

| Verdict | Means | Lands as |
|---|---|---|
| 🟢 ok | healthy | a row in the status issue |
| 🔵 watch | worth knowing, nothing to do (stale, dormant, unmaintained transitive) | a row in the status issue |
| 🟡 act | a deterministic action exists (a fixed version of a vulnerable package) | a row; the action module carries it out |
| 🔴 escalate | a human decision (archived dependency, license change, phantom action pin) | its own issue, deduplicated by key |

## Identity

Every EDamLabs repository declares what it is in `pyproject.toml`, and its fleet entry repeats it; the `drift`
module escalates any contradiction.

```toml
[tool.edamlabs]
kind = "lib"        # what it ships
family = "binding"  # what it is
```

| `kind` | Ships | Release |
|---|---|---|
| `lib` | an importable package | PyPI, trusted publishing |
| `service` | a long-running process | a Docker image on GHCR |
| *`desktop`, next* | *a desktop application* | *signed binaries* |

| `family` | Is | Projects |
|---|---|---|
| `eager` | the eager series: EDamLabs' own products, the `e-` line | e-serde, e-voice |
| `binding` | a Python binding of a third-party engine, kept compatible with its upstream | etrafilatura, anytomd, gliner |
| `infra` | the organisation's own machinery | esteward |

The `e` of a binding's name (etrafilatura) marks the EDamLabs build, not the eager series.

## Modules

| Module | Checks | Sources |
|---|---|---|
| `deps` | every watched dependency: repository archived or dormant, registry status (PEP 792), release age, yanked latest, license change; every locked package: vulnerabilities and unmaintained notices | GitHub, PyPI, crates.io, OSV (RustSec included) |
| `security` | every action pinned by commit SHA in the workflow paths resolves to a real commit | GitHub |
| `drift` | `[tool.edamlabs]` in `pyproject.toml` declares the fleet entry's `kind` and `family`: missing acts, contradicting escalates | GitHub |

More modules (upstream, release, docs, community) follow the same contract: a fleet entry in, a
`Report` out.

## The fleet

One file per project, `fleet/<repo>.toml`:

```toml
repo = "edamlabs/etrafilatura"
kind = "lib"                       # lib (PyPI) | service (Docker)
family = "binding"                 # eager | binding | infra
modules = ["deps", "security", "drift"]

[deps]
release_age_days = 540             # watch past this
push_age_days = 365
lockfiles = ["uv.lock", "Cargo.lock"]

[[deps.watch]]
name = "trafilatura-rs"
repo = "https://github.com/nchapman/trafilatura-rs"
registry = "https://crates.io/crates/trafilatura"
license = "Apache-2.0"             # a different license escalates

[security]
paths = [".github/workflows"]      # where workflow files live
```

## Running

`fleet.yml` runs the whole fleet daily (05:17 UTC) and on demand (`workflow_dispatch`, optionally one project),
with the `eself-maintenance` app token scoped to each project's repository.

```bash
make check                        # lint, types, import contracts, tests at 100 % coverage
make run P=etrafilatura           # dry run with your gh token: verdicts on screen, nothing published
uv run esteward run etrafilatura --publish   # what the fleet job does
```

Decisions and their evidence: [`docs/decisions.md`](docs/decisions.md).
