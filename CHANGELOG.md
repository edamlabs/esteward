# Changelog

All notable changes to esteward are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The engine is consumed from git and never published, so nothing here is released: `[Unreleased]` records the
milestones it has reached.

## [Unreleased]

### Added

- M5 · community (`TODO_community`): deterministic triage of a repository's open third-party issues and pull
  requests. A `community` label marks what the engine has seen, an issue with no body earns a request for the
  reproduction it lacks and the `needs-repro` label, idleness past `stale_days` earns the `stale` label and a
  warning naming the day it closes, and idleness past the warning closes the item with its idle age. Insiders,
  automation and drafts are never spoken about; the engine never approves and never merges a third-party pull
  request. Enabled on all six fleet entries.
