# Changelog

All notable changes to this project are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [0.8.0] — 2026-11-07

### Added

- **`valid_until` temporal validity field.** `record_memory`/`roco record` take an optional ISO-8601 `valid_until` timestamp (migration `0006_add_valid_until.sql`, nullable, no default-row impact). There is no separate `valid_from` field — a memory is considered valid starting from its own existing `created_at`, automatically. `get_memory` and `retrieve_context` surface `valid_until` plus a computed `expired: true/false` flag whenever `valid_until` is set (both fields omitted for the common no-expiry case, matching the existing null-field-omission convention). Not auto-excluded from ranking — an expired memory is still returned, just flagged, so the caller/agent decides what to do with it, same fail-open posture as the `abstract` field below.
- **`link_memories` MCP tool.** Exposes the existing `create_link` core function (previously CLI-only via `roco link`) over MCP, so an agent can flag two memories as `contradicts` or `duplicate_of` without shelling out. `retrieve_context` items now carry a per-item `contradicted_by: [id, ...]` field whenever a `contradicts` link exists, naming the specific conflicting memory — previously only an aggregate `meta.contradicted` count was available, with no way to tell *which* returned items were the conflicting pair.
- **L0 `abstract` field.** `record_memory` asks a local Ollama model (`lfm2.5:350m`) for a one-line summary of each new memory, stored in a new nullable `abstract` column (migration `0005_add_abstract.sql`) and surfaced by `retrieve_context`. The call runs outside the SQLite transaction and is fail-open: a model outage or bad response stores `abstract = NULL` and never blocks the write. `httpx` is now a core dependency.

## [0.7.0] — 2026-11-04

### Added

- **`statement`/`assumptions`/evidence `description` caps raised from 500 to 750 characters.** Revisits the 2026-08-31 decision to hold the line at 500 (roco's terseness was deliberate, and dimag already routes longer content elsewhere) — the migration mechanism to change a SQLite CHECK constraint (create-copy-drop-rename table rebuild) was proven safe against a populated fixture DB back then but never actually shipped as a real migration. New `migrations/0004_widen_statement_limits.sql` rebuilds `memory` and `evidence` with the wider caps, preserving every row, `memory_path`/`evidence`/`memory_link` foreign keys, the FTS5 index, and the AUTOINCREMENT sequence (reseeded explicitly — a table-rebuild loses `sqlite_sequence`'s row for the old table name). `--statement`/`--why`/`--assumptions` CLI help text updates automatically (sourced from the same constants). Covered by a new `test_db.py` case that upgrades a populated version-3 database and checks FK integrity, row survival, and FTS lookup post-migration.

## [0.6.1] — 2026-08-10

### Fixed

- **`roco mcp` broke on every fresh install.** The `mcp` optional dependency was pinned `mcp>=1.28` with no upper bound; upstream shipped `mcp` 2.0.0, which renamed `mcp.server.fastmcp.FastMCP` to `mcp.server.mcpserver.MCPServer`. `mcp_server.py` still imports the old path, so `pip install robo-cortex[mcp]` succeeded but `roco mcp` failed immediately with a misleading "the 'mcp' package is not installed" (the real, swallowed error was `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`). Pinned to `mcp>=1.28,<2.0` to restore working installs; migrating to the new `MCPServer` API to support `mcp` 2.0.0 is separate future work.

## [0.6.0] — 2026-08-10

### Fixed

- **The pre-commit hook's own documented recovery still failed for an already-`active` memory.** 0.5.1 fixed `reverify()` to hash working-tree content instead of HEAD, but missed that `active` was never in its own allowed-transition set — so `roco status <id> activate --reason "..."` (the hook's unconditional printed remedy) was an illegal `active`->`active` transition and always raised `IllegalTransitionError` whenever the blocked memory's stored status was still `active`, which is the common case: `refresh_staleness` only compares stored hashes against HEAD, and a still-staged edit doesn't move HEAD, so the status column never actually left `active` before the retried commit. `--no-verify` was the only way past the block. `active` is now a legal self-transition target, running the same `reverify()` recapture as any other path to `active`. Found live in `/srv/robo-rag`, tracked as roco memory #5.
- **`roco list --json` never included `last_verified_at`.** `list_memories()` hardcoded its selected columns without it, so any diagnosis of a stuck re-verification loop via `roco list --json` always reported the field as missing/`None` regardless of whether re-verification had actually run — a contributing factor in how the bug above was diagnosed. Now included.

### Added

- **`activate` now works as a manual re-verification of an already-`active` memory**, not just as a `provisional`/`needs_review` -> `active` promotion. Previously guaranteed to fail with `IllegalTransitionError` when the current status was already `active` — see Fixed above.

## [0.5.1] — 2026-08-09

### Fixed

- **`activate` didn't clear a pre-commit block on staged-but-uncommitted changes.** The pre-commit hook's own message tells you to run `roco status <id> activate --reason "..."` then commit again — but `activate` (via `reverify()`) recaptured each linked path's blob hash from HEAD, not from the staged content that triggered the block. If the edit was still staged (the normal case: hook fires, you review, you activate, *then* commit), HEAD hadn't moved yet, so `reverify` just recomputed the same pre-edit hash it already had. The hook fired again on the retried commit with the identical list, and only `git commit --no-verify` actually got past it. `reverify()` now hashes the working-tree content (falling back to HEAD only when the path is missing on disk), which matches staged content in the normal `git add` case and matches HEAD in the already-committed case — so it fixes the staged-block loop without changing behavior for the post-commit self-heal path the existing tests cover.

## [0.5.0] — 2026-08-03

### Fixed

- **Global-scope commands no longer require a local repo store.** `show`, `search`, `retrieve`, `status`, `link`, `evidence add`/`verify`, `list`, and `record --scope global` used to unconditionally call `open_store()` first — hard-failing with "not inside a git repository" (or "run init first") even when the operation only ever touched `~/.cortex/global.db`, which is repo-independent by construction (ARCHITECTURE.md §2). In practice this meant a purely global lookup (`roco show <global-id>`) only worked if you happened to be standing inside *some* already-initialized repo — any one would do, but finding one by trial and error was real, reported friction. These commands now resolve the repo store lazily and fall back to global-only when none is available; `--scope repo` explicitly requested with no repo store still fails, now with a clear, actionable message (`no repo store available (not inside a git repo, or 'robo-cortex init' never ran there) -- pass --repo, or drop --scope repo to also check the global store`) instead of either crashing or silently returning nothing.
- **`record --scope global`** specifically no longer resolves a repo at all (not even lazily) — global records can't carry `--path` (already validated), so `repo_root` was accepted but never actually used for that branch. `roco record --scope global ...` now works from anywhere, including outside any git repo entirely.

### Added

- **Character limits in `record --help`.** `--statement` (500), `--why` (300), and `--assumptions` (500) previously enforced their limits only at write time, with no hint in `--help` — the only way to learn the ceiling was to hit the `ValidationError` and shorten. Now documented inline.

## [0.4.3] — 2026-07-31

### Fixed

- **Silent wrong-store mutation on id collision.** Repo-local and global stores are independent autoincrement sequences, so a repo memory and a global memory can share the same numeric id. `roco status`/`link`/`evidence verify` (and the SDK/MCP equivalents), when called without `--scope`, used to silently pick whichever store hit first (local, by convention) — so e.g. `roco status 10 activate` could flip the wrong, unrelated memory to `active` with no error and no indication anything was off. `find_memory_store`/the new `find_evidence_store` now detect the collision and raise a clear `id N exists in both repo and global stores -- pass --scope repo or --scope global to disambiguate` error instead of guessing. `status`/`link` also now echo which store they acted on (`Memory 10 (global) -> active`) so a resolved-but-unintended target is visible immediately. Found live during normal usage.

### Added

- **Global store id partitioning.** New global memories/evidence/links now start at id 1,000,000,000+ (bumped in place, no renumbering of existing rows) so future ids can no longer collide with any repo-local store's ids — the same bug class above, closed structurally going forward. Ids assigned before this change can still collide with existing repo-local ids; the collision-detection fix above is what catches those.

## [0.4.2] — 2026-07-26

### Changed

- **`list_affected` MCP tool documentation.** Gave the tool a full `description=` (matching the other high-value tools) and per-parameter `Field` descriptions for `diff_range`/`staged`/`working`. The description now states concretely what the tool returns, excludes terminal-status memories, and — most importantly — spells out *when* to reach for it versus `retrieve_context` and `search_memory` (it is diff-driven, mapping a code delta to the memories that depend on it, not a task- or keyword-driven read). Documentation only; no behavior change. Raises the tool's Glama quality-score dimensions (behavior, completeness, parameters, purpose, usage guidelines).

## [0.4.1] — 2026-07-15

Adds the `mcp-name` ownership-verification marker to the README, required to publish robo-cortex to the official MCP Registry (registry.modelcontextprotocol.io). No functional changes.

## [0.4.0] — 2026-07-15

First public PyPI release. All changes below were already complete in the unpublished `0.3.1` local build — this version bump exists solely to mark the public debut, not to introduce new behavior.

## [0.3.1] — 2026-07-15

Fixes driven by a second internal self-audit, done before the first PyPI publish, plus a round of follow-ups from an independent Ubuntu evaluation. Still unpublished — `0.3.0` never shipped to PyPI, so this is a local version bump only, to make a freshly-built checkout distinguishable when testing.

### Fixed

- **`git hash-object`** crashed on any linked path whose name starts with `-` (interpreted as a flag) — every `affected` call, and therefore the pre-commit hook, would fail on such a file. Fixed with a `--` separator; `affected` also now looks up linked memories *before* hashing touched paths, and batches remaining hashes through a single `git hash-object --stdin-paths` call instead of one subprocess per file.
- **Pre-commit hook** bound the first `roco`/`robo-cortex` found on `PATH` at install time without checking it was actually robo-cortex — a name collision with an unrelated `roco` package (see README's PyPI name-collision note), or the bound binary later disappearing (venv removed, `pipx uninstall`), silently broke every future commit. Install now verifies the candidate binary with `--version` before binding it; the installed hook itself checks the binary still exists at commit time and fails open (with a clear stderr message and the bypass instructions) instead of blocking every commit with a bare "not found."
- **`retrieve`/`search`/`affected`** crashed with a raw `sqlite3.OperationalError: attempt to write a readonly database` on a read-only `.cortex/memory.db` (read-only checkouts, some CI setups) — these are read paths that also do incidental writes (staleness refresh, usage tracking). They now degrade gracefully: writes are skipped, the read still returns its result, and a `warnings` entry in `meta` says so.
- **`ROBO_CORTEX_GITEA_TOKEN`** was sent to any configured Gitea URL regardless of scheme. `http://` URLs (except localhost) now refuse to send the token and degrade evidence to `unverifiable: gitea_insecure_url`, unless `ROBO_CORTEX_GITEA_ALLOW_HTTP=1` is set.
- **Comment-only and whitespace-only Python edits** spuriously flipped linked memories to `needs_review` (EVALUATION.md §8 measured a 100% rate on its sample). `.py` paths now get a token-stream equivalence check (stdlib `tokenize`, comments and blank lines ignored, indentation still significant) before falling back to the exact-hash flag; a cosmetic-only change silently re-anchors the stored blob hash instead of flagging. See EVALUATION.md §8a for the re-measured rate and ARCHITECTURE.md §5.3.1 for the mechanism. Any tokenization failure (syntax error, non-UTF8 content) still falls back to the original flag-on-any-change behavior — fail-safe, not fail-silent.
- **`record --path <not-yet-committed-file>`** error message now names the actual remedies (commit the file first, or record without `--path` and attach it later with `--add-path`) instead of just stating the refusal.

### Added

- **`ROBO_CORTEX_NO_GLOBAL`**: opt out of the cross-project global store entirely (CLI and MCP both skip opening `~/.cortex/global.db`) — for anyone who wants `retrieve`/`search` scoped strictly to the current repo, with no implicit cross-project channel.
- **`roco record <id> --add-path <path>`**: attach a path to a memory after the fact. `--update-path` only relinked a path already attached; there was no way to attach one to a memory that had none — the workaround (record without `--path`, commit the file, attach it) was blocked. Closes the gap; found during an independent Ubuntu evaluation.
- **`roco init --global`**: explicitly create/open the scope-B store (`~/.cortex/global.db`) instead of leaving it to be created implicitly by the first `record --scope global` call.
- **`roco completion bash`**: static, zero-dependency shell completion, generated by introspecting the real argparse tree. Completes subcommand names and each subcommand's own flags; nested sub-subcommands (`hooks install`, `evidence add`) and flag values aren't completed yet (documented KISS limit).
- **Colored status output**: `list`/`show`/`retrieve` color-code memory status (green=active, yellow=provisional/needs_review, red=terminal statuses) on an interactive terminal. Respects `NO_COLOR`; `--json` output is unaffected.
- **`roco hooks install --post-commit`**: optional, informational-only hook (runs `affected --diff-range HEAD~1..HEAD` after each commit, never blocks) — `--post-commit` also works with `uninstall`/`status`, independently of the pre-commit hook.

### Performance

- `refresh_staleness` now caches the last-checked HEAD SHA (`meta` table, migration `0003`) and skips the `git ls-tree -r HEAD` walk entirely when HEAD hasn't moved since the last call — the common case for consecutive `retrieve`/`search` calls between commits.
- FTS candidate scoring is now capped (`FTS_CANDIDATE_LIMIT = 200`, ordered by relevance) — bounds the per-candidate `get_memory` cost on stores with a very large number of matching memories.

## [0.3.0] — 2026-07-14

Release-readiness pass, driven by a critical internal self-audit done before the first public release. Every change below fixes something the audit found; nothing here is speculative.

### Fixed

- **`roco import --repo <path>`** (repo-scoped memories) crashed with `AttributeError: 'tuple' object has no attribute 'execute'`. The connection-selection logic was rewritten so the two stores (repo, global) are passed as two explicit connection factories instead of one scope-keyed selector — the class of bug is now structurally impossible, not just fixed once.
- **`roco import`** with a JSONL line missing `created_at`/`last_verified_at` crashed with a raw `sqlite3.IntegrityError`. Missing timestamps now default sensibly.
- **`roco import`** bypassed all of `record`'s validation — a `scope=global` line with no `assumptions`, or an invalid `type`/`confidence`, was either silently inserted or crashed on a raw `CHECK` constraint. Import now runs every line through the same validator `record` uses; invalid lines are skipped with a clear warning.
- **`retrieve`/`search`/`affected`** on a git repository with zero commits crashed with a raw `subprocess.CalledProcessError` (exit 128 from `git ls-tree HEAD`). Now raises a clear "this repository has no commits yet" error; `roco init` also warns proactively at init time.
- **`roco merge`** with a missing input file printed a raw Python traceback. `cli/app.py`'s `main()` now has a last-resort handler: any exception not already a clean `RoboCortexError` prints a one-line message instead of a stack trace (`ROBO_CORTEX_DEBUG=1` still gets the full traceback when you want it).
- **`roco merge`**'s conflict messages didn't match the format documented in `EXPORT_IMPORT.md`. Aligned (`"picked high over medium"`, `"confidence tie, picked new"`).
- **`--type` help text** in `roco record --help` listed `bug` and `insight` as example types — neither was ever a valid `--type` value.

### Changed — Python SDK rewritten (breaking)

The pre-0.3.0 SDK (`robo_cortex.sdk`) was a subprocess wrapper around the CLI that didn't actually work: `search()` sent its argument in the wrong shape, `record()` had no `assumptions` parameter so `scope="global"` was unreachable, and every exception was swallowed into an `{"error": ...}` dict nothing checked for.

It's rewritten from scratch to call `robo_cortex.core` directly — the same pattern the MCP server already used — with no subprocess involved:
- `RoboCortex.retrieve/record/search/list_memories/get_memory` call core functions in-process.
- `record()` gained the missing `assumptions` parameter.
- Real exceptions (`RoboCortexError` subclasses) now propagate to the caller.

This is a breaking change to the SDK's error-handling contract, accepted deliberately: the old SDK had no working callers to protect. See [PYTHON_SDK.md](PYTHON_SDK.md).

### Added — real enforcement: `roco hooks`

Earlier README drafts described three enforcement layers (git hooks, a code decorator, a CI/CD gate) before any of them existed in code. The first one now exists for real:

- `roco hooks install` writes a pre-commit hook that blocks a commit touching paths linked to a non-terminal memory, with a clear review prompt. `roco hooks uninstall` / `roco hooks status` complete the set.
- A pre-existing, non-robo-cortex pre-commit hook is never silently overwritten — install refuses without `--force`, and `--force` chains the existing hook rather than replacing it.
- The bypass (`git commit --no-verify`) is explicit and documented, not hidden.
- The code decorator and a first-class CI-gate subcommand are **not** built yet — see `ROADMAP.md`'s "Enforcement layers not yet built" for why, and [docs/ci-example.yml](docs/ci-example.yml) for a copy-paste GitHub Actions job covering the CI use case today with the existing `roco affected` command.

### Changed — documentation

- **README.md** rewritten around the differentiators the project actually has (git-aware staleness detection, evidence-based confidence, zero dependencies, lifecycle audit trail) instead of the three fictional enforcement layers, an unrelated `urlshort` reference, and an unqualified "It can't [forget]" claim. Cites the real, modest token-savings numbers from `EVALUATION.md` (2.7–10.6%) instead of an invented "~1,500 tokens saved" figure.
- Every command in the README's Quick Start was run by hand, in sequence, on a clean repository before being written down (including catching that the *previous* README's own Quick Start commands didn't pass `--assumptions`/`--confidence` and would have failed validation).
- **PYTHON_SDK.md** rewritten to match the new SDK: real `TYPES` values, `why_it_matters` instead of `why`, no more phantom "subprocess timeout" troubleshooting section.

### Test coverage

- `tests/test_transfer.py` (new): pins every bug fixed above as a regression test, plus baselines for behavior that was already correct.
- `tests/test_sdk.py` (new): round-trip coverage for the rewritten SDK, including the `scope=global` + `assumptions` path that was previously unreachable.
- `tests/test_hooks.py` (new): installs a real pre-commit hook and runs actual `git commit` against it — confirms it blocks, that `--no-verify` bypasses it, and that an unrelated commit isn't blocked.

## [0.2.0]

- Added `roco export` / `roco import` / `roco merge` for cross-project knowledge sharing (JSONL format).
- Added the (later found non-functional — see 0.3.0) Python SDK.
- Added `roco` as a shorthand alias for `robo-cortex` (same binary, two entry points).
- Added usage tracking (`last_used_at`, `use_count`) to the memory schema, laying groundwork for a future `prune` command (see ROADMAP.md).

## [0.1.0]

Initial release. Core memory lifecycle (record/retrieve/search/status/evidence/link), git-anchored staleness detection, scope A (repo) and scope B (global) stores, MCP server, optional Gitea evidence verification. See `EVALUATION.md` for the release-gate evaluation this version shipped against.
