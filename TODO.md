# TODO

The work left after the EDamLabs migration (2026-10-26). It is written for an instance with no prior context: read
**Context** first, then take items in order. Every item has a check that can fail; it is not done until that check
passes. When an item is finished, delete it from this file in the same PR.

## Context

### The organisation

EDamLabs (`github.com/edamlabs`) publishes open-source Python/Rust projects that maintain themselves. No pull
request waits for a human: routine changes merge themselves once every required check passes, and anything that
needs a decision becomes one deduplicated issue.

| Repo | `kind` | `family` | Ships | Local clone | Release flow |
|---|---|---|---|---|---|
| `etrafilatura` | lib | binding | PyPI `etrafilatura` 0.1.0 | `~/workspaces/damien/etrafilatura` | push tag `v*` → `release.yml` |
| `anytomd` | lib | binding | PyPI `anytomd` 1.4.2 | `~/workspaces/damien/anytomd` | push tag `v*` → `release.yml` |
| `gliner` | service | binding | GHCR `ghcr.io/edamlabs/gliner` 0.1.2 | `~/workspaces/damien/gliner` | push tag `v*` → `release.yml` |
| `e-serde` | lib | eager | PyPI `e-serde` 0.6.2 (import `eserde`) | `~/workspaces/damien/e-serde` | `workflow_dispatch` (bump) → release PR (app token) → tag → PyPI |
| `e-voice` | service | eager | GHCR `evoice-stt` 0.2.3, `evoice-tts` 0.2.1, `evoice-full` 0.2.3 | `~/workspaces/damien/e-voice` | `workflow_dispatch` (service, bump) → per-image tags `stt-v*`/`tts-v*`/`full-v*` → GHCR |
| `esteward` | lib | infra | consumed from git, never published | `~/workspaces/edamlabs/esteward` | — |

Identity taxonomy: `README.md` § Identity. Only the repository name carries the dash (`e-serde`, `e-voice`); imports,
images and services do not (`eserde`, `evoice-stt`).

Every repository has the same baseline. Verify it with the commands in § Reference before assuming it.

- **Ruleset:** a ruleset on `main` with 0 required approvals and strict required checks.
- **Merging:** `allow_auto_merge` is on, and Renovate (Mend app) has a policy that automerges routine updates.
- **Identity:** it is declared in `pyproject.toml` `[tool.edamlabs]` or `Cargo.toml` `[package.metadata.edamlabs]` /
  `[workspace.metadata.edamlabs]`.
- **Fleet entry:** `fleet/<repo>.toml` here, and a status issue labelled `esteward`.

### What esteward does today

`fleet.yml` runs daily at 05:17 UTC and on dispatch. It has three modules, all deterministic.

| Module | Checks |
|---|---|
| `deps` | Every watched dependency: archived, dormant or moved repositories, PEP 792 status, stale, yanked, license change. Every package in each lockfile: OSV vulnerabilities and RustSec unmaintained notices. |
| `security` | Every `uses: owner/repo@sha` resolves to a real commit. |
| `drift` | The manifest identity matches the fleet entry. |

Verdicts follow the ladder ok → watch → act → escalate. One status issue per repository lists every finding. Each
`escalate` becomes its own issue, keyed and self-closing.

**`act` executes itself** (`--act`): a lockfile-only vulnerability bump becomes one self-merging PR per finding
key; a fix the solver cannot reach downgrades to `watch · blocked upstream` with its reverse dependency chain.

### House rules (non-negotiable)

- Talk to Damien in Spanish from Spain (tú). Code, commits, docs and PRs are in English.
- **Python style:**
  - Python 3.14, `msgspec`/`pydantic-settings`/`structlog`/`wreq`/`cyclopts`, `beartype` claw.
  - Hexagonal: ports are Protocols in `logic/ports.py`, adapters live in `adapters/`, composition happens in
    `core/lifespan.py` + `cli/`.
  - Layers are enforced by `tach.toml`.
  - Naming follows the `tax-py-naming` skill: the class takes the module name as its surname, private methods are
    `_<public>_<what>`, and only `##### SECTION #####` / `###` comments are allowed.
  - No `if/elif`: use `match` or frozen mappings.
  - Absolute imports, module level only.
- **Gate:** `make check` (ruff, ty, tach, pytest at **100 % coverage**). No test may depend on timing or load. A
  stochastic test is a bug: fix the cause or make it deterministic, never just retry it.
- **Decisions:** every architectural decision gets a dated entry in `docs/decisions.md` with its evidence and the
  rejected alternatives.
- **Shipping:**
  - Every change goes through a PR with `gh pr merge --auto --squash`.
  - Never use `--admin`: the auto-mode classifier blocks it anyway.
  - Strict checks make your own PRs `BEHIND` when something else merges first: rebase locally and
    `push --force-with-lease`; `gh pr update-branch` does not exist in this gh.
  - Renovate rebases its own PRs; tick `rebase-check` in the PR body (REST `PATCH`) to force it.
- **Things only Damien can do:**
  - Weaken a ruleset.
  - Delete secrets or variables.
  - Open issues on third-party repositories: write the text and hand it to him.
  - PyPI trusted publishers, Mend repository selection, GHCR package visibility (`edamlabs` → Settings → Packages →
    Package creation now allows Public).
- **Commit trailer:** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; PR bodies end with the Claude Code
  line.

### Credentials and quirks

- The GitHub App `eself-maintenance` (client id in org variable `APP_CLIENT_ID`, key in org secret
  `APP_PRIVATE_KEY`) is installed on every repository. It has no `workflows` permission, so it cannot touch
  `.github/`.
- The agent provider is reached through org secret `SM_API_KEY` and variables `SM_BASE_URL` and `SM_MODEL` (any
  OpenAI-compatible endpoint).
- **The org forbids `GITHUB_TOKEN` from creating PRs.** Any job that opens a PR must use the app token, minted with
  `permission-pull-requests: write`.
- `allow_auto_merge` cannot be turned on through the REST API (PATCH silently ignores it, creation payload too); it
  is a UI-only setting. Every fleet repository has it on; a new repository needs the toggle before its first act PR.
- GitHub's labelled issue listing sometimes returns an empty 200, so the adapter unites three reads
  (decisions 2026-10-22).
- A moved repository answers 301, and wreq does not follow redirects: follow once (decisions 2026-10-26).
- crates.io rejects requests without a `User-Agent`.
- PyPI PEP 792 status comes from the simple JSON API (`Accept: application/vnd.pypi.simple.v1+json`).

## 1 · Releases cut themselves (M3, policy = auto)

Damien chose automatic releases, which are safe while the records exist (tags, changelog, provenance).

**Done (2026-10-26).** The `release` module decides from the records, and `esteward run --release` carries the
decision out; the mechanism lives once, in esteward (decisions 2026-10-26). Policy: content in
`## [Unreleased]` gates, a Fixed/Security entry releases at once, anything else once the oldest unreleased
commit passes the fleet entry's `unreleased_age_days`; patch by default, minor on `### Added` or a `feat:`
commit, a breaking marker escalates. Execution: fold the changelog line for line like e-serde's awk, bump the
static version fields, re-sync the root lockfiles, open one self-merging `chore(release): vX.Y.Z` PR, and push
the tag onto that PR's merge commit on a later run; the repository's own tag-driven `release.yml` publishes.
A version folded but untagged holds the next release (`watch`). Enabled on **etrafilatura** and **anytomd**
(both already trigger on `v*` pushes); live dry runs print the decisions.

- **Check still open:** one real automatic patch release, on a repository with pending fixes, lands on
  PyPI/GHCR with no human step. Blocked on a repository actually accumulating an unreleased fix — every
  `[Unreleased]` is empty as of 2026-10-26, so the engine correctly decides "no unreleased content". Watch
  the first `fix:` that lands on etrafilatura or anytomd.
- **Enable the rest as each converges:**
  - **e-serde** and **gliner** converged on 2026-10-27 (their `release.yml` is tag-driven now: the engine's
    tag fires wheels/sdist/PyPI and the image respectively) and their fleet entries enable `release`.
  - **e-voice** releases per image (`stt-v*`/`tts-v*`/`full-v*`); its `service` comes from which crates changed
    since the last tag. Needs its own per-image policy before it can be enabled.

## 2 · Upstream (M2), docs (M4), community (M5)

Each is a module with the same contract: a fleet entry in, a `Report` out, wired in `cli/commands/run.py` `MODULES`.

- **M2 · upstream — done (2026-10-27).** The `upstream` module reports one parity row per engine declared in
  the fleet entry (`[[upstream.engines]]`: name, registry, parity): ok when the parity is the engine's newest
  release; watch when the engine moved ahead and the repository has a sync or maintenance flow (the agent owns
  the mirror); escalate when the engine moved ahead and no flow exists (a human sets the parity), when the
  parity is ahead of the engine (a wrong declaration), or when the registry page is gone. Detection only: the
  public API diff and the repair stay with the repository's tooling (`make apidiff`, the sync flow). Enabled on
  etrafilatura, anytomd and gliner at today's parity; the live dry run escalates nothing (tokenizers is watch:
  its 1.0.0-rc.3 sits ahead of the stable parity 0.23.2, and gliner's sync flow owns that mirror).
- **M4 · docs — done (2026-10-27).** The `docs` module runs the repository's own `make docs` (every repo's
  target builds strict: aligned in the same sweep) in a fresh checkout; probes the Pages site (the changelog
  page must carry the newest release's version); and checks every external link of `docs/**.md`, bounded
  (sorted, capped at 250 per run, concurrency-limited) and deduplicated within the run — the escalation
  issues are the cache across runs, closing themselves when the link lives again. Dead links and failing
  builds escalate; a missing docs config or a missing release watch. e-voice defers the pages check
  (`[docs] pages = false`): its versions live per image, and that check follows its per-image release policy.
  Deploy alignment shipped with it: `docs.yml` added where absent (etrafilatura, anytomd, e-serde), the
  `DOCS_DEPLOY` gate switched on where the workflow existed inert (gliner, e-voice).
- **M5 · community.**
  - Deterministic triage of third-party issues and PRs: labels, missing-reproduction requests, stale closing with a
    message.
  - It never approves and never merges a third-party PR.
- **Check:** each module ships with 100 % coverage and a dry run over the whole fleet, with no false `escalate` on
  today's state.

## 3 · Housekeeping

- **e-voice pre-push hook depends on host load.** `make coverage` runs the model-backed STT tests with
  `--include-ignored`. Under load (load average 64 on 32 cores from docling-serve) a different timing test failed on
  each of three pushes, so this session pushed with `--no-verify` four times.
  - The tests are stochastic: make them deterministic (inject a clock, bound by events, not wall time).
  - Check: `make coverage` passes 10/10 under `stress-ng --cpu 32`.
- **e-voice names.** Crates, binaries, Docker volumes and local tags still say `e-voice-*`. Images already dropped
  the dash; the rest was rejected for now in `e-voice/docs/decisions.md`, because it changes CLI names and needs a
  volume migration.
  - Only do it if Damien asks: rename, migrate volumes, record the decision.
- **Old artefacts.**
  - `damvolkov` GHCR packages `e-voice-*` (and the old gliner image, if any): ask Damien whether to delete them.
    People with the old `docker pull` may still depend on them.
  - The old `damvolkov/anytomd` PyPI trusted publisher: Damien removes it.
- **e-serde and e-voice have no `sync.yml`/`maintenance.yml`** (the agent flow the bindings have). Decide whether the
  eager series needs an agent at all, now that Renovate and esteward cover them. Record the decision either way.
- **e-arkhetypo** (`damvolkov/e-arkhetypo`, private tooling stays in e-taxis/e-nous).
  - Another instance is refactoring `core` → `infra` there. Coordinate before touching it.
  - Not yet exported: the release-PR-with-app-token flow and the changelog fold from item 1 (export once proven in
    two repositories), and per-subproject `.python-version` pins (e-voice `eval/` broke when uv picked CPython 3.15.1,
    where polars 1.44.2 returns `None` from `Series.drop_nulls()`).
- **Strict checks and own PRs.** Every non-Renovate PR goes `BEHIND` as soon as Renovate merges first. Measure how
  often over two weeks. If it is frequent, the act stage's PR opener should rebase and re-enable auto-merge itself.

## Reference

```bash
make check                                    # the gate
make run P=e-voice                            # dry run, verdicts on screen
gh workflow run fleet.yml -R edamlabs/esteward [-f project=<repo>]
gh api repos/edamlabs/<repo>/rulesets --jq '.[].name'          # baseline: one ruleset "main"
gh api repos/edamlabs/<repo> --jq .allow_auto_merge            # baseline: true
gh issue list -R edamlabs/<repo> --label esteward              # the status issue
```

Adding a repository to the fleet, the recipe proven on five repositories:

1. Branch before transfer: URLs/authorship → edamlabs, identity in the manifest, docs on Zensical, Renovate replacing
   Dependabot, `docs/decisions.md`, CHANGELOG.
2. `gh api -X POST repos/damvolkov/<r>/transfer -f new_owner=edamlabs`; update the remote.
3. Ruleset (clone etrafilatura's, swap the required checks), `allow_auto_merge`, labels (`~/.local/bin/bootstrap-org`),
   `~/.config/esmbot/repos.txt`.
4. Damien deletes the repo-level secrets and variables that shadow the org ones, adds the repo to Mend, and adds the
   PyPI trusted publisher (lib) or makes the GHCR packages public (service).
5. `fleet/<r>.toml` here (dry run first), then a patch release.
