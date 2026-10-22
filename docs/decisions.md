# Decisions

### 2026-10-22 · A public engine of its own, in edamlabs

**Decision.** Maintenance of EDamLabs projects lives in `edamlabs/esteward`, public. e-taxis and e-nous stay
private and personal: they mount projects and harnesses, they do not maintain them.

**Evidence.** The fleet is public (libraries and dockerizable services); the engine acting on it is shared
infrastructure, not personal tooling. A private engine could not be installed by public repositories' CI
without a cross-identity token.

**Rejected.** `taxis maintain` (mixes a personal toolchain with organisation infrastructure); a PyPI package
(see below).

### 2026-10-22 · Consumed from git, never published

**Decision.** esteward is not published to PyPI. Workflows check it out at the commit they run from.

**Evidence.** Engine and workflow versions can never drift; a release is a git tag; nobody outside EDamLabs
installs it.

**Rejected.** PyPI: a second version to keep aligned and a release pipeline with no consumer.

### 2026-10-22 · The fleet lives here

**Decision.** Every project's maintenance contract is `fleet/<repo>.toml` in this repository; projects carry
only the thin callers that events require (PR and issue events fire in their own repository).

**Evidence.** One place to read and change what the organisation maintains; a module change and its
configuration change land together.

**Rejected.** A `maintain.toml` in each project: N copies of the same thresholds to keep in step.

### 2026-10-22 · Autonomous, deterministic, one issue per incident

**Decision.** Verdicts are `ok | watch | act | escalate`, decided by thresholds and by what hosts, registries
and advisory databases report. Escalations open one issue each, keyed by a marker, updated while they
persist and closed when they clear; one pinned status issue per repository holds the rest.

**Evidence.** Phantom-pin detection verified on damvolkov/e-arkhetypo: 10 pins naming no commit found, matching
the manual audit; etrafilatura: 6 healthy dependencies, 14 resolving pins, 212 locked packages queried.

**Rejected.** Pull requests for every finding (a human would review a junior's work); an LLM judging health (a
deterministic check exists for every signal).

### 2026-10-22 · Runtime typing with beartype

**Decision.** `beartype_this_package()` in the package hook; ruff's TC001–TC003 disabled.

**Evidence.** beartype resolves annotations at runtime; imports moved under `TYPE_CHECKING` would not resolve.

**Rejected.** Static checking only (the house checks types twice).

### 2026-10-22 · Uncached loggers

**Decision.** `cache_logger_on_first_use=False`, stderr resolved per call.

**Evidence.** A cached logger kept a closed stderr across captured runs (order-dependent test failures); a CLI
emits tens of events, the cost is nil.

**Rejected.** Caching with per-test resets (fixes tests, keeps the redirection hazard in production).
