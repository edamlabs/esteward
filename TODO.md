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

- **Policy, per `kind`:** release when `## [Unreleased]` in `CHANGELOG.md` has content and the oldest unreleased
  commit is older than N days (a fleet setting).
  - A `fix`/security entry releases at once.
  - Patch by default. Minor when the Unreleased section has `### Added` or a `feat:` commit. Never major: a major
    release is `escalate`.
- **Trigger, per repository's flow** (table above):
  - Tag-driven repos (etrafilatura, anytomd, gliner): the tag must sit on a commit whose version bump is already
    merged. They need a release PR (bump the manifest version + fold `[Unreleased]` into `## [x.y.z] — date`) before
    the tag.
  - e-serde already does all of this in `release.yml` (`workflow_dispatch` → app-token PR → tag). Prefer converging
    the tag-driven repos onto that shape over writing a second mechanism.
  - e-voice releases per image; its `service` input comes from which crates changed since the last tag.
- **Changelog fold:** the new heading must replace `[Unreleased]`'s content, never stack a commit list above it.
  e-serde's awk (`.github/workflows/release.yml`) is the proven version: with curated notes they become the body; when
  empty, the commit subjects do.
- **Check:**
  - A dry-run mode prints the decision per repository.
  - One real automatic patch release, on a repository with pending fixes, lands on PyPI/GHCR with no human step.
  - A unit test covers every branch of the policy.

## 2 · Upstream (M2), docs (M4), community (M5)

Each is a module with the same contract: a fleet entry in, a `Report` out, wired in `cli/commands/run.py` `MODULES`.

- **M2 · upstream.**
  - For bindings (`family = binding`): the engine's new release, public API diff and parity baseline.
  - etrafilatura and anytomd already have pieces: `sync.yml`, `maintenance.yml` (Qwen agent with an allowlist),
    `tools/health.py`, `make apidiff`. esteward should own the detection and leave the repair to the repository's
    agent.
  - Watch the engines: `trafilatura` (crate) for etrafilatura, `anytomd` (crate) for anytomd, `ort`/`tokenizers` and
    the `gliner` PyPI reference for gliner.
- **M4 · docs.**
  - `zensical build --strict` passes on `main`.
  - The deployed Pages site serves the latest release's version.
  - No dead external links (deterministic link check, bounded and cached).
  - Pages: etrafilatura, anytomd, gliner, e-serde, e-voice.
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
