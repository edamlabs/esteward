# Changelog

All notable changes to esteward are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The engine is consumed from git and never published, so nothing here is released: `[Unreleased]` records the
milestones it has reached.

## [Unreleased]

### Added

- Fleet: `e-jev` onboarded (`edamlabs/e-jev`, service · eager, moved from `damvolkov` on 2026-10-28) with
  `deps`, `drift` and `community`; its manifest declares `[tool.edamlabs]` and `drift` reports ok.
  `security`, `docs` and `release` stay off until the repo carries workflows and a docs site — its image is
  still a private user package, `ghcr.io/damvolkov/e-jev`.
- M5 · community (`TODO_community`): deterministic triage of a repository's open third-party issues and pull
  requests. A `community` label marks what the engine has seen, an issue with no body earns a request for the
  reproduction it lacks and the `needs-repro` label, idleness past `stale_days` earns the `stale` label and a
  warning naming the day it closes, and idleness past the warning closes the item with its idle age. Insiders,
  automation and drafts are never spoken about; the engine never approves and never merges a third-party pull
  request. Enabled on all six fleet entries.

### Changed

- Detached from the personal toolchain: the engine's public record no longer names it. The decision log
  speaks of "the personal toolchain" and "a private blueprint repository" where it named the repositories;
  the blueprint's pending work left `TODO.md` — it belongs to that repository's own plan, not to the
  watcher's.
- README: badge layout, description and identity line standardized on the e-serde template; the verdict ladder
  kept as its own table under the identity line. Done in `TODO_standardize_readme` across the fleet.
