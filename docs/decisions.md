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

### 2026-10-22 · Issue listings are read three times; duplicates converge

**Decision.** `GithubAdapter.issues` unites three reads of the listing; the planner keeps the oldest issue per
dashboard or incident key and closes the rest as duplicates.

**Evidence.** The second fleet run on etrafilatura opened a second status issue (#14 beside #13). Measured with
fresh installation tokens, scoped and unscoped: the labelled listing answered an empty 200 in 2 of 16 reads.
Three united reads bring a false empty from ~12 % to ~0.2 %; convergence repairs what remains on the next run.

**Rejected.** Trusting one read (duplicates); storing issue numbers outside GitHub (state to keep in sync);
GitHub search (eventually consistent as well).

### 2026-10-26 · Moved repositories are followed once and watched

**Decision.** The GitHub adapter follows one 301/302/307/308 from a moved repository; the deps module turns a
moved repository into a `watch` finding naming the new location; a second redirect raises.

**Evidence.** esteward's own fleet entry crashed on `jcrist/msgspec`, which answers 301 since it moved to
`msgspec/msgspec`: wreq does not follow redirects, and the redirect body has no `archived` field.

**Rejected.** Enabling wreq's redirect following globally (hides the move the fleet should record).

### 2026-10-26 · An advisory's fix is the fix of the locked version's branch

**Decision.** The OSV adapter reports as `fixed` the end of the `introduced <= locked < fixed` interval holding the
locked version (versions compared with `packaging`, semver's `-0` read as the version itself); a version in an open
interval has no fix; an unparsable version falls back to the first fix listed.

**Evidence.** anytomd's `webpki-roots` 1.0.9 was reported "fixed in 0.26.11" — the fix of the 0.26 branch; its
branch is fixed in 1.0.10.

**Rejected.** The first fix listed (wrong across release branches); a semver library per ecosystem (PEP 440
ordering holds for the released versions OSV lists).
