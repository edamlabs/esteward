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

## Modules

| Module | Checks | Sources |
|---|---|---|
| `deps` | every watched dependency: repository archived or dormant, registry status (PEP 792), release age, yanked latest, license change; every locked package: vulnerabilities and unmaintained notices | GitHub, PyPI, crates.io, OSV (RustSec included) |
| `security` | every action pinned by commit SHA in the workflow paths resolves to a real commit | GitHub |

More modules (upstream, release, docs, community, drift) follow the same contract: a fleet entry in, a
`Report` out.

## The fleet

One file per project, `fleet/<repo>.toml`:

```toml
repo = "edamlabs/etrafilatura"
kind = "lib"                       # lib (PyPI) | service (Docker)
modules = ["deps", "security"]

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
