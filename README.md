<p align="center">
  <a href="https://github.com/edamlabs/esteward/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/edamlabs/esteward/ci.yml?label=test" alt="CI"></a>
  <a href="https://img.shields.io/badge/python-3.14-166b7e"><img src="https://img.shields.io/badge/python-3.14-166b7e" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/edamlabs/esteward?color=166b7e" alt="License"></a>
</p>

Self-maintenance engine for EDamLabs projects: deterministic dependency, upstream, release, docs, security and community modules.

Part of the **EDamLabs infrastructure**: EDamLabs' own machinery ([EDamLabs families](https://github.com/edamlabs/esteward#identity)).

| Verdict | Means | Lands as |
| --- | --- | --- |
| 🟢 ok | healthy | a row in the status issue |
| 🔵 watch | worth knowing, nothing to do (stale, dormant, unmaintained transitive, blocked upstream) | a row in the status issue |
| 🟡 act | a deterministic action exists (a fixed version of a vulnerable package) | a row; with `--act`, a self-merging PR — or a downgraded verdict explaining why it cannot |
| 🔴 escalate | a human decision (archived dependency, license change, phantom action pin) | its own issue, deduplicated by key |

## Identity

Every EDamLabs repository declares what it is in its manifest — `pyproject.toml` `[tool.edamlabs]`, or for a Rust project `Cargo.toml` `[package.metadata.edamlabs]` — and its fleet entry repeats it; the `drift` module escalates any contradiction.

```toml
[tool.edamlabs]
kind = "lib"        # what it ships
family = "infra"    # what it is
```

| `kind` | Ships | Release |
| --- | --- | --- |
| `lib` | an importable package | PyPI, trusted publishing |
| `service` | a long-running process | a Docker image on GHCR |
| *`desktop`, next* | *a desktop application* | *signed binaries* |

| `family` | Is | Projects |
| --- | --- | --- |
| `eager` | the eager series: EDamLabs' own products, the `e-` line | e-serde, e-voice |
| `binding` | a Python binding of a third-party engine, kept compatible with its upstream | etrafilatura, anytomd, gliner |
| `infra` | the organisation's own machinery | esteward |

The `e` of a binding's name (etrafilatura) marks the EDamLabs build, not the eager series.

## Modules

Every module follows the same contract: a fleet entry in, a `Report` out.

| Module | Checks | Sources |
| --- | --- | --- |
| `deps` | every watched dependency: repository archived or dormant, registry status (PEP 792), release age, yanked latest, license change; every locked package: vulnerabilities and unmaintained notices | GitHub, PyPI, crates.io, OSV (RustSec included) |
| `security` | every action pinned by commit SHA in the workflow paths resolves to a real commit | GitHub |
| `drift` | `[tool.edamlabs]` in `pyproject.toml` declares the fleet entry's `kind` and `family`: missing acts, contradicting escalates | GitHub |
| `upstream` | each declared engine against its newest release: parity current, engine ahead (the repository's sync flow owns the mirror, or a human when none exists), a wrong parity declaration, a vanished registry page | crates.io, PyPI, GitHub |
| `docs` | `make docs` (the strict Zensical build) passes on main; the deployed Pages site serves the newest release; no dead external link in `docs/` | the checkout, GitHub Pages, every linked site |
| `release` | `## [Unreleased]` content gates a release; a Fixed/Security entry releases at once, anything else once the oldest unreleased commit passes the fleet's age; patch by default, minor on `### Added` or `feat:`, a breaking marker escalates; a folded version without its tag is carried | GitHub (changelog, tags, commits) |
| `community` | every open third-party issue and pull request: the `community` label it has never been given, the reproduction an empty issue lacks, the `stale` warning past the entry's idle age and the close past its own grace | GitHub |

## Act

With `--act`, the engine carries out the `act` findings whose fix is a **lockfile-only** bump: the ecosystem's solver (`cargo update --precise` / `uv lock --upgrade-package`) runs in a fresh checkout, the bumped lockfile is re-parsed as the evidence, and the change lands as one PR per finding key (`esteward/act/<key-slug>`) that merges itself when every required check passes. Re-runs update the open PR instead of duplicating it, and the status row links it.

When the solver cannot reach the fix, the reverse dependency tree (`cargo tree -i` / `uv tree --invert`) decides: an intermediate package pinning the vulnerable range downgrades the finding to `watch · blocked upstream` with the chain as evidence (`zip 0.6.6 ← npyz 0.9.1 ← e-voice-tts`); the project's own manifest blocking the fix escalates, since that range is a human decision.

## Release

With `--release`, the decision becomes the release. The engine folds `[Unreleased]` into `## [x.y.z] — date` — line for line the fold e-serde's release workflow proved — bumps the static version fields, re-syncs the root lockfiles, and opens one self-merging `chore(release): vX.Y.Z` PR. A later run pushes the tag once that PR has merged, onto its merge commit; the repository's own tag-driven workflow builds and publishes. A version folded but untagged holds the next release (`watch`), and anything that would need a major version escalates instead. The module is enabled per fleet entry, as repositories converge onto the tag-push flow.

## Community

The `community` module triages what a stranger opened: it labels the item `community` once it has seen it, asks for the reproduction an empty issue lacks (`needs-repro`), marks an item idle past `stale_days` as `stale` with a warning naming the day it closes, and closes it once that warning ages out past `close_days` — with a reply dropping the label instead. New activity always wins.

Automation and insiders are never triaged. `author_association` cannot tell them apart — the engine's own status issues and Renovate's answer as `CONTRIBUTOR` or `NONE` — so the author's login decides, and a draft pull request is left alone. The engine never approves and never merges a third-party pull request: no such operation exists in its vocabulary. Triage is carried out by `--publish` like the dashboard, and a dry run prints each row as `planned` instead.

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
```

## Running

`fleet.yml` runs the whole fleet daily (05:17 UTC) and on demand (`workflow_dispatch`, optionally one project), with the `eself-maintenance` app token scoped to each project's repository.

```bash
make check                        # lint, types, import contracts, tests at 100 % coverage
make run P=etrafilatura           # dry run with your gh token: verdicts on screen, nothing published
uv run esteward run etrafilatura --act --release --publish   # what the fleet job does
```

Decisions and their evidence: [`docs/decisions.md`](docs/decisions.md).
