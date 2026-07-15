# robo-cortex — Architecture

**Gate artifact for Gate B.** Companion documents: [`schema.sql`](schema.sql) (v1
migration), [`MCP_TOOLS.md`](MCP_TOOLS.md) (tool contracts),
[`PYTHON_SDK.md`](PYTHON_SDK.md) (Python SDK for programmatic access),
`PHASE4_CRITERIA.md` (pre-written evaluation criteria, an internal process
document not included in this release). Builds on `PHASE1_RESEARCH.md` (Gate A,
approved, same status). No implementation code exists before this document is
approved.

**Access methods:**
- **CLI:** `robo-cortex retrieve|record|search ...` (subprocess calls)
- **MCP:** `robo_cortex.retrieve_context|record_memory|search_memory` (agent tools)
- **Python SDK:** `from robo_cortex import retrieve, record` (direct programmatic)

## 1. Data model

**Type taxonomy — reduced from 8 to 7.** The mission's minimum list includes
"experiment/outcome" and "dead end" as separate concepts. They are merged:
a **dead end is not a type, it is an outcome** — an `experiment` or
`hypothesis` memory whose status becomes `abandoned`, which then triggers the
dead-end compression flow (§6) that creates a new `lesson` memory linking back
to it. This is a direct reduction, not a new mechanism: the lifecycle model
the mission already requires (`abandoned` state) does this job without a
dedicated type. Final types: `fact`, `decision`, `convention`, `hypothesis`,
`experiment`, `lesson`, `open_question`.

**No tags table.** `type` + `scope` + FTS5 search over `statement` substitute
for free-form tags in the MVP. A tags table is cheap to add later; it is
omitted now because nothing in Phase 3's vertical slices demonstrably needs it
— KISS checklist: the concrete problem ("find related memories") is already
solved by search.

**Fields** (see `schema.sql` for exact types/constraints):
`id`, `type`, `scope` (`repo` | `global`), `statement` (≤ 500 chars),
`why_it_matters` (≤ 300 chars, optional), `status`, `status_reason`,
`confidence` (`low`|`medium`|`high`, explicit, never inferred),
`assumptions` (scope=`global` only — see §5), `created_at`,
`last_verified_at`, `created_by` (free-text attribution, e.g. `"agent"` or a
name — no auth system in the MVP).

Linked paths, evidence, and inter-memory links are separate tables (§2–§4) —
a memory has zero or more of each, which a single wide row can't model
cleanly.

`evidence_strength` is **never stored** — it is derived at query time from
the `evidence` rows attached to a memory (§4.2), so it can never drift out of
sync with the evidence that justifies it.

## 2. Storage layout

- **Scope A (repository memory):** `.cortex/memory.db` at the repository
  root, found via `git rev-parse --show-toplevel` or an explicit `--repo`
  flag. Never assumes it runs inside robo-cortex's own checkout (Stage 3).
- **Scope B (reusable memory):** `~/.cortex/global.db`, same schema and
  migration runner, outside any repository by construction.
- Retrieval consults both stores and merges results (§5).

**Open question 1 — committed or gitignored: `.cortex/` is gitignored by
default.** The mission frames this as a trade-off (versioning-for-free and
portability vs. history pollution and merge conflicts), but for a single
SQLite file the merge-conflict side is disqualifying, not just a cost: git
cannot three-way-merge a binary database, so two branches that both write
memories produce an unresolvable conflict on every merge, not an occasional
annoying one. "Free" versioning that breaks every merge is not free. Team
sharing is deferred to an explicit export/import flow (JSONL, one line per
memory — the same shape limpet's `.limpet/memory.jsonl` and memento-mcp's
`.memento/memories/*.json` both converge on independently) as a `ROADMAP.md`
candidate, not built in the MVP because nothing in Phase 3's scenarios
requires team sync.

**Consequence, stated explicitly:** memory is per-clone. A fresh `git clone`
of a repository with months of accumulated `.cortex/memory.db` history starts
with an *empty* store — nothing about the memories themselves travels with
the code. This makes the export/import roadmap item dual-purpose, not a
team-sharing nicety: the same JSONL flow is also how one person's second
machine, or a fresh clone after a disk wipe, recovers memory that would
otherwise be gone. Until that ships, the practical mitigation is the seeding
session (`docs/PHASE1_RESEARCH.md`'s cold-start answer) — cheap enough to
repeat per clone, which is exactly why it was chosen over a bespoke importer.

**`init` writes its own `.gitignore` entry.** Rather than merely document
"gitignore `.cortex/`" and hope the user remembers, `robo-cortex init`
appends a `.cortex/` line to the repository's `.gitignore` itself (creating
the file if absent, and doing nothing if an equivalent entry already matches)
and reports what it did. This removes the one manual step between "the
architecture recommends gitignoring" and "the binary database file actually
never gets committed by accident."

**Cold storage stays inside the one SQLite file**, as a `cold_storage` table
(§6), not separate flat files. The mission fixes "one database file" as a
technical decision; a second storage location for verbose dead-end detail
would violate that for no concrete gain — the table is still trivially
inspectable with `sqlite3 .cortex/memory.db "select content from
cold_storage where id = ?"`, and "not in normal packs" is satisfied simply by
never including `cold_storage` rows in the FTS index or a retrieval query.

## 3. Evidence model

`evidence` table, one memory to many evidence rows: `kind` (`test_output` |
`ci` | `commit` | `gitea_pr` | `gitea_issue` | `free_text` |
`cold_storage_ref`), `description` (≤ 500 chars, human-readable, so a rotted
`ref` still leaves useful context — this is the mechanism that makes a rotten
link degrade to "unverifiable" instead of silent nonsense), `command`
(nullable — the re-runnable proof command), `expected_outcome` (nullable),
`ref` (nullable — commit SHA, `pr:123`, `issue:45`, or a `cold_storage` row
id), `status` (`unverified` | `verified` | `unverifiable`), `created_at`,
`checked_at`.

**robo-cortex never executes a stored `command`.** Only the calling agent
does, when handed the command by `verify_evidence` (§7) during
re-verification. This is a deliberate security boundary, not an oversight: a
memory store that auto-executes arbitrary stored strings is a code-execution
primitive sitting behind "untrusted input" (§10). A stored `command` and
`expected_outcome` are exactly as untrusted as any other memory content —
`verify_evidence`'s output carries the same "data, not instructions" framing
as `retrieve_context` (§7), so the agent is expected to read a command before
running it, not execute it blindly because robo-cortex handed it over.
Re-verification means: `verify_evidence` hands back `command` +
`expected_outcome` unchanged for command-backed evidence (and, for
Gitea-backed evidence, performs the one explicit, opt-in network check itself
— §9); the agent runs the command and calls `attach_evidence` or
`change_status` with the result.

### 3.1 Evidence strength (mechanical, not judged)

Per memory: `base = max(kind_weight)` over its evidence rows, where
`kind_weight` is `free_text`→0.4, `commit`/`gitea_pr`/`gitea_issue`→0.7,
`test_output`/`ci`→1.0, `cold_storage_ref`→0.4 (it points at detail, not
proof). Strength `= min(1.0, base + 0.1 × (count − 1))` — more independent
evidence nudges strength up, capped so five free-text notes never outrank one
test run. `unverifiable` evidence rows still count (rot doesn't erase that a
claim was once checked) but do not raise `checked_at`-based recency signals.

## 4. Lifecycle

States: `active`, `provisional`, `needs_review`, `superseded`, `invalidated`,
`abandoned`, `archived` — all seven are kept; each is exercised by a distinct
mechanism already required elsewhere in the mission (provisional→active on
first evidence, needs_review is the invalidation signal, superseded/
invalidated are the two "final, deliberate" outcomes, abandoned triggers
dead-end compression, archived is the manual "stop showing me this" escape
hatch). Removing any one would need to be re-invented as a flag on another
field, so none are cut.

**Allowed transitions** (enforced in code, illegal ones rejected with a clear
error — Stage 7):

```
provisional   -> active, needs_review, abandoned
active        -> needs_review, superseded, invalidated, archived, abandoned
needs_review  -> active (heal), superseded, invalidated
superseded    -> archived                         (terminal otherwise)
invalidated   -> archived                          (terminal otherwise)
abandoned     -> archived                          (terminal otherwise)
archived      -> (none — fully terminal)
```

`needs_review -> active` is the only auto-transition (revert-healing, §5.3);
every other edge is a deliberate `change_status` call with a required reason.

**`active -> abandoned` (added post-v0.1.0).** `attach_evidence` (§3)
auto-promotes `provisional -> active` on first evidence, unconditionally.
Without this edge, an experiment or hypothesis became permanently
unabandonable the moment evidence was attached — including the evidence
that *proves* it was a dead end (e.g. a benchmark showing a caching attempt
made things slower). "Record the finding, then abandon" is the natural
order an agent works in; the state machine should not force "abandon
first, evidence-less, then attach evidence to an already-terminal-adjacent
memory" instead. Found via real dogfooding on a test project, not review.

## 5. Retrieval, ranking, and context packs

### 5.1 Ranking formula (open question 3)

A memory's score is a weighted sum of six components in `[0, 1]`, each
printed individually with `--explain`: **text_match** (0.35 — the FTS5 BM25
rank, min-max normalized within the current candidate set so it never depends
on an absolute score scale that changes between SQLite versions);
**path_overlap** (0.20 — fraction of the task's given paths found among the
memory's linked paths, exact or directory-prefix match; 0 when no paths are
given or the memory has none, never a penalty); **confidence** (0.15 —
low/medium/high mapped to 0.33/0.66/1.0, the author's explicit setting, never
inferred); **evidence** (0.15 — §3.1's mechanical strength); **status**
(0.10 — 1.0 for active/provisional, 0.7 for needs_review; superseded,
invalidated, abandoned, and archived are **excluded from ranking entirely**,
not merely down-weighted, since they are not offered as current working
knowledge by default); and **recency** (0.05 — exponential decay from
`last_verified_at`, halving every 90 days). Weights are fixed defaults,
overridable via config, and always sum to 1.0. `--explain` prints all six
numbers and their sum next to the final score, so the formula is debuggable
by inspection, not just by reading this paragraph.

### 5.2 Context packs

Input: a free-text task description plus optional repository paths. Process:
FTS5 candidate query (both stores, scope B filtered by assumption match,
§5.4) → score and rank → pack best-first within budget (default 15 items,
~2,000 estimated tokens via `len(text)/4` on the full rendered item including
evidence summaries) → attach the honesty envelope. Budgets are configurable
per the mission; defaults are the mission's numbers.

**Honesty envelope**, on every pack, no exceptions:
```json
{
  "matched": 11, "returned": 7,
  "omitted": [{"reason": "budget", "count": 4}],
  "needs_review": 2, "contradicted": 1
}
```
No code path truncates without recording why in `omitted`.

### 5.3 Blob-hash invalidation and revert healing (open question 2)

At `record` and at `verify`, each linked path's blob hash is captured via
`git rev-parse HEAD:<path>` (free — no diff scanning) into `memory_path`. A
background-free check — run lazily on `retrieve`/`search`/`affected`, not via
a daemon — recomputes current hashes and compares:

- Hash differs → `needs_review`, `status_reason = "path_changed:<path>@<commit>"`.
- Path vanished at HEAD → `needs_review`, `status_reason = "path_missing:<path>"`.
- Hashes match again (including a path that reappeared) → **heal**: status
  returns to whatever it was before the flag (tracked via a
  `pre_review_status` column set only when entering `needs_review`, cleared on
  heal). Only `superseded`/`invalidated`/`abandoned`/`archived` are final —
  filesystem churn, branch switches, and mid-rebase states are never death
  sentences.

**Renames are followed, but only on cryptographic certainty, never on
similarity.** When a linked path `P` with stored hash `H` vanishes at HEAD,
the staleness check does one more lookup before giving up: scan `git
ls-tree -r HEAD` for any path whose current blob hash equals `H` exactly.

- **Exactly one match** → auto re-link: `memory_path.path` is updated to the
  new location, `blob_hash` stays `H` (it never changed — that's the whole
  point), and the memory's status is untouched, because nothing the memory
  described actually changed. This is zero-heuristic: an exact SHA match is
  not "probably the same file", it is *provably byte-identical content*, so
  there is no confident-but-wrong risk to guard against.
- **Zero or multiple matches** → `needs_review: path_missing`, reason string
  includes the recovery command (`git log --follow --diff-filter=R --
  <path>`) for the agent to inspect and re-link manually via `record
  --update-path`. Multiple matches (e.g. an empty file duplicated at several
  paths) are deliberately *not* auto-resolved — picking one would be a guess,
  which is exactly the failure mode this mechanism exists to avoid.

What is still **not** built, and stays a documented limitation: similarity-
based rename detection (git's own `-M` heuristic, or anything content-diff-
based) for the case where a file was renamed *and* edited in the same
commit — the hash no longer matches anything, so it falls to
`path_missing` like any other edit-and-move. Symbol (AST) anchoring is the
same story at finer grain — a documented future upgrade, not built now,
justified in `ROADMAP.md`.

**Path-less memories** (conventions, most decisions, all `lesson`s) get an
age-based signal instead: `needs_review: stale_unverified` when
`last_verified_at` is more than `stale_after_days` (default 180, configurable)
in the past. This is a much weaker signal than a blob-hash mismatch — it is
surfaced identically in the envelope but never silently conflated with "we
know this changed."

#### 5.3.1 Comment/whitespace tolerance for Python

EVALUATION.md §8 measured the consequence of exact-hash comparison directly: a
comment-only addition and a trailing-blank-line addition each spuriously
flipped their linked memory to `needs_review` — a 100% observed spurious-flag
rate on that sample. Left unaddressed, this erodes the hook's enforcement
value in practice: memories linked to actively-edited files stay perpetually
`needs_review`, and the realistic response is `git commit --no-verify` out of
habit, which defeats the point.

For `.py` paths only, a hash mismatch is no longer an automatic flag. `_check_path`
(`core/invalidate.py`) first asks `core/semantic.py` whether the two blobs
tokenize to the same *significant* token stream — stdlib `tokenize`,
`COMMENT` and `NL` tokens dropped, everything else (including `INDENT`/
`DEDENT`) kept. Indentation stays part of the comparison deliberately: it is
semantic in Python, which is why a `git diff -w` whitespace-blind heuristic
was rejected as a fix in the original open-question discussion — a consistent
re-indent is a real edit to the file's structure, not noise.

- **Tokens match** → `reanchored`, not `flagged`: the stored `blob_hash` is
  silently updated to the new blob and a `reanchored` entry is added to
  `refresh_staleness`'s change list (auditable, but non-blocking — it never
  touches `status`). The next refresh sees the file as unchanged.
- **Tokens differ, or tokenization fails for any reason** (syntax error,
  non-UTF8 content, anything unexpected) → falls back to the original
  `path_changed` flag. This is fail-safe by construction: the function raises
  on any tokenizer error rather than returning an ambiguous result, and the
  caller catches broadly and treats every exception as "not proven
  equivalent." A memory is never silently kept `active` on a file robo-cortex
  couldn't actually analyze.
- Non-`.py` paths are entirely unaffected — exact-hash comparison, unchanged.

This is intentionally narrower than symbol/AST anchoring (still a documented
future upgrade, see `ROADMAP.md`): it only proves "nothing meaningful
changed," never "this specific memory's claim is still true." A memory whose
linked function's *logic* changed still flags, correctly — see
`tests/test_invalidate.py::test_semantic_variable_rename_still_flags` and
`::test_indentation_change_still_flags` for the two contra-cases confirmed
still flagging, and EVALUATION.md §8a for the re-measured rate.

### 5.4 Scope-B assumption matching (open question 4)

**Revised design.** An earlier draft gated scope-B inclusion on a FTS5
text-match score normalized against the candidate set (min-max). Rejected on
review: min-max normalization is *relative*, so the best-scoring candidate in
a weak or single-candidate set normalizes to ~1.0 and clears any threshold —
precisely when nothing actually matches, which is the failure Phase 4
scenario 4 exists to catch. Worse, because `assumptions` sat in the same FTS
row as `statement`/`why_it_matters`, a memory could clear the gate purely on
statement-text similarity with no assumption term corroborated at all. Both
problems share one root cause: using a relative, whole-row search score to
answer a question that needs an absolute, field-specific one.

**Replacement: an absolute, assumption-specific gate, separate from
ranking.** `assumptions` is a comma-separated list of short condition
phrases (e.g. `"single-user, local-first, low write concurrency"` — three
phrases) and is a **plain column, not part of the FTS index** — `memory_fts`
covers only `statement`/`why_it_matters` for every memory regardless of
scope, so text-match ranking (§5.1) never sees assumption text and can't be
satisfied by it.

The gate itself, run once per scope-B candidate before it is scored at all:
for each assumption phrase, strip stopwords (`a`, `an`, `the`, `for`, `with`,
`is`, `are`, `of`, `to`, `in`, `on`, `and`, `or`), and check whether every
remaining word appears as a whole word (case-insensitive) in the task
description text. A phrase is `matched` or `not matched` — binary, no partial
credit per phrase. `fraction_matched = matched_phrases / total_phrases`. The
memory enters the scope-B candidate set only if `fraction_matched ≥
assumption_threshold` (default **1.0** — every stated phrase must be
corroborated; configurable down, deliberately conservative by default because
the mission's stated risk is a project-specific win silently becoming a
universal rule, not the reverse). Once past the gate, a scope-B memory is
scored identically to scope-A candidates via §5.1's formula — the gate is a
precondition, not a ranking input.

`--explain` (and `get_memory`'s `score_breakdown` for a scope-B memory)
prints the gate per phrase:
```json
"assumptions_gate": {
  "phrases": [
    {"text": "single-user", "matched": true},
    {"text": "local-first", "matched": true},
    {"text": "low write concurrency", "matched": false}
  ],
  "fraction_matched": 0.67, "threshold": 1.0, "passed": false
}
```
This is plain word-overlap, not semantic matching — stated as the trade-off
it is, and it is exactly what Phase 4 scenario 4 tests directly: that the
gate fires on a plausible match and does not fire on an unrelated one.

### 5.5 Usage tracking

**Lazy side effect of `retrieve_context`.** Each memory included in a returned
context pack increments `use_count` and updates `last_used_at` (a single timestamp
for the whole pack, via a batched `UPDATE` per store to avoid per-row write
overhead). This is distinct from `search_memory`, which is an exploratory tool
and does not update usage statistics — only productive retrieval (memories
actually delivered to a task) counts as "use."

This enables future data-driven decisions about archiving stale lessons: after
accumulating weeks or months of real usage data, a pruning flow can identify
memories that haven't been retrieved in N days (via `last_used_at`) or have
been retrieved rarely (via `use_count`), and transition them to `archived`
status or export them to a backup for potential later recovery. The mechanism
is currently observation-only; a `prune` command is a documented future task
in `ROADMAP.md`.

## 6. Consolidation, contradiction, and dead-end compression

`memory_link` table: `from_id`, `to_id`, `link_type` ∈ {`contradicts`,
`supersedes`, `duplicate_of`, `lesson_from`}.

- **Duplicate detection:** at `record` time, an FTS5 query of the new
  statement against existing active/provisional memories in the same scope;
  above a similarity threshold, a `duplicate_of` link is written
  automatically and both memories are flagged in `list --needs-consolidation`
  — **never auto-merged**. A human or agent resolves it explicitly (usually
  via `change_status --supersede`).
- **Contradiction:** an explicit `link --contradicts A B` call (CLI/MCP).
  Both memories stay visible and both carry the flag in every pack's honesty
  envelope until one supersedes the other; the `contradicts` link itself is
  never deleted, only joined by a later `supersedes` link — history is never
  overwritten.
- **Dead-end compression:** `change_status <id> abandoned --reason "..."`
  requires the reason; the agent then `record`s a new `lesson`-type memory
  and links it `lesson_from -> <abandoned id>`. Verbose detail (full
  experiment logs, transcripts) goes into `cold_storage`, referenced by a
  `cold_storage_ref` evidence row on the lesson. The lesson is short (subject
  to the same statement cap as everything else) and enters normal retrieval;
  the abandoned experiment itself is excluded from default retrieval by the
  status filter (§5.1) but remains fully inspectable via `show`/`list
  --status abandoned`.

**Closing the forgetting gap:** compression only happens if whoever abandons
a memory remembers the second step (`record` the lesson, link it back).
Nothing enforces that today, so an `abandoned` memory with no incoming
`lesson_from` link is a dead end that silently stayed dead — knowledge lost,
not preserved, the opposite of the mission's "preserve lessons, not noise"
principle. `list --abandoned-without-lesson` (§8) makes this queryable
directly: every `abandoned` memory with zero incoming `lesson_from` links,
sorted oldest-first. It is a plain list filter, not a new status or a new
table — the data to answer it already exists in `memory` + `memory_link`, so
this is a query, not a new component.

## 7. MCP tool design

Eight tools — the mission's six-tool sketch ("retrieve", "record",
"attach/inspect evidence", "change status", "search", "list affected") splits
"attach/inspect evidence" into `attach_evidence` (write) and folds "inspect"
into a general `get_memory` (read one memory + its evidence + score
components against an optional task — needed for the CLI's `show` UX and for
printing `--explain` components, and reused by both the write-path
confirmation flow and debugging). One tool is added beyond the mission's
sketch: `verify_evidence`, because §3 and §9 both need a named, explicit
re-verification entry point (§9's Gitea posture specifically requires that
network calls happen only from one explicit, opt-in action, not as a side
effect of any read path) — without it those two sections would be describing
a mechanism that has no actual tool behind it. Full contracts, inputs/
outputs, failure behavior, and worked examples: [`MCP_TOOLS.md`](MCP_TOOLS.md).

1. `retrieve_context` — budgeted, ranked pack for a task (§5.2).
2. `record_memory` — create a memory, optional linked paths (validated to
   exist at HEAD, dead links refused loudly) and optional evidence.
3. `attach_evidence` — add evidence to an existing memory.
4. `get_memory` — full detail: fields, evidence, links, and (if a task is
   given) its score breakdown.
5. `change_status` — supersede/invalidate/abandon/archive, reason required,
   transition matrix (§4) enforced.
6. `search_memory` — unbounded-ish exploration search (area/task/concept),
   distinct from `retrieve_context`'s strict budget: for debugging and CLI
   `list`/`search`, not for feeding an agent's working context.
7. `list_affected` — memories put at risk by a diff (default: working tree +
   staged; accepts an explicit commit range).
8. `verify_evidence` — re-check one evidence row. For command-backed
   evidence, returns `command`/`expected_outcome` unchanged (the agent runs
   it and reports back via `attach_evidence`/`change_status`); for
   Gitea-backed evidence (`gitea_pr`/`gitea_issue`), performs the live API
   check itself and updates `evidence.status` to `verified` or
   `unverifiable` — the one place in the entire tool set allowed to make a
   network call, and only when a caller explicitly asks (§9, §10).

**Stdio purity:** `robo-cortex mcp` hands stdio directly to the official
`mcp` SDK; every other write goes to stderr (already true of the Stage 0
stub). **Prompt-injection posture:** every tool description states that
returned memory content is data, not instructions, and pack items are
rendered in a structure (JSON fields, not concatenated prose) that does not
invite an agent to treat them as directives.

## 8. CLI command set

CLI and MCP share one core library (`robo_cortex.core`) — every command below
is a thin wrapper over the same functions the MCP tools call; no logic is
implemented twice. Every command supports `--json` for machine-readable
output; default output is a human-readable table/summary.

| Command | Arguments (key ones) | Exit codes |
|---|---|---|
| `init` | `[--repo PATH]` — also appends `.cortex/` to `.gitignore` (§2), creating it if absent, no-op if already covered | 0 ok · 1 not a git repo · 2 already initialized |
| `record` | `--type --scope --statement --confidence [--path]... [--why] [--assumptions]` | 0 ok · 1 validation failure (dead path, over-length) · 2 usage |
| `record --update-path` | `ID --old-path P --new-path P'` — manual re-link when auto-relink (§5.3) found zero or multiple exact-hash matches | 0 ok · 1 not found/path missing at HEAD · 2 usage |
| `record --add-path` | `ID --add-path P` — attach a new linked path to an existing memory; the workflow for a file that didn't exist at HEAD yet when the memory was first recorded (record without `--path`, commit, then attach) | 0 ok · 1 not found/dead path/already linked/scope=global · 2 usage |
| `record --batch` | reads JSON Lines from stdin, one `record` payload per line, all-or-nothing per line (a bad line is reported and skipped, good lines still commit — each line is its own transaction) | 0 ok (see JSON summary: `{"created": N, "failed": [{"line": 3, "error": "..."}]}`) · 2 usage |
| `show` | `ID [--explain-against TASK]` | 0 ok · 1 not found |
| `list` | `[--status] [--scope] [--type] [--needs-consolidation] [--abandoned-without-lesson]` | 0 ok (0 rows is still exit 0) |
| `retrieve` | `--task TEXT [--path]... [--budget-items N] [--budget-tokens N] [--explain]` | 0 ok |
| `search` | `--query TEXT [--scope] [--type] [--status]` | 0 ok |
| `status` | `ID {supersede\|invalidate\|abandon\|archive} --reason TEXT [--by ID]` | 0 ok · 1 illegal transition · 2 usage |
| `evidence add` | `ID --kind K --description TEXT [--command] [--expected] [--ref]` | 0 ok · 1 not found |
| `evidence verify` | `EVIDENCE_ID` — the CLI form of `verify_evidence` (§7): re-runs nothing itself, hands back `command`/`expected_outcome` for command-backed evidence, performs the live check for `gitea_pr`/`gitea_issue` evidence | 0 ok · 1 not found |
| `affected` | `[--diff-range A..B \| --staged \| --working]` (default: working tree + staged combined, matching `MCP_TOOLS.md`'s `list_affected`) | 0 ok |
| `link` | `ID1 {contradicts\|duplicate-of} ID2` | 0 ok · 1 not found/self-link |
| `mcp` | — | 0 clean shutdown (already implemented, Stage 0) |

**Exit code 3 is reserved across every command** for `SQLITE_BUSY` surfaced
as "another writer is active, retry" — never a stack trace, distinguishable
by scripts from a validation failure (1) or usage error (2).

**`record --batch` and the cold-start seeding session.** This is the
concrete mechanism `docs/PHASE1_RESEARCH.md`'s seeding-session answer runs
on: an agent doing cold-start onboarding reads existing docs/ADRs/
`CLAUDE.md` once, emits one JSON object per candidate memory, and pipes the
whole batch through `record --batch` instead of one CLI invocation per
memory — the same `record` validation (dead-path refusal, length caps) runs
per line, just without per-line process overhead. It is not an importer: it
still requires the agent to have read and judged the source material line by
line before emitting JSON, exactly as an interactive `record` call would.

## 9. Gitea integration (optional layer)

Evidence kinds `gitea_pr`/`gitea_issue` store `ref` as `pr:<number>` /
`issue:<number>`. A single `robo_cortex.gitea` module wraps the Gitea REST
API (base URL and token from `ROBO_CORTEX_GITEA_URL` /
`ROBO_CORTEX_GITEA_TOKEN`, both optional) and is called **only** from
`verify_evidence` (§7, CLI: `evidence verify`) — never by `record`,
`retrieve`, or any core read path. The actual Gitea API surface (endpoint paths, auth header
shape, pagination) is verified from Gitea's own API docs at Stage 10
implementation time, not invented here. If the API is unreachable or
unconfigured, the evidence `status` becomes `unverifiable` and everything
else keeps working — Stage 10's exit criteria require the full suite to pass
with zero Gitea configuration present. This stage may be descoped to
`ROADMAP.md` with a one-line justification if it threatens the timeline (the
mission marks it optional); nothing else in the architecture depends on it.

## 10. Security

- **Retrieval output is data, not instructions** (§7) — the core
  prompt-injection defense, since stored memories are untrusted input from
  past agent sessions.
- **No command execution** — stored `command` strings are handed back, never
  run by robo-cortex itself (§3).
- **Path validation** — every linked path is checked to resolve inside the
  repository root at record time; absolute paths and `..` traversal are
  rejected at one choke point shared by CLI and MCP.
- **Parameterized SQL only** — no string-built queries anywhere in the core.
- **No network calls from the memory core.** The only network-capable code
  is the opt-in Gitea module (§9), never imported by `retrieve`, `record`,
  `search`, or `affected`.
- **Rotten evidence degrades, never lies** — a `ref` that no longer resolves
  (rebased commit, deleted PR) flips `evidence.status` to `unverifiable`
  without touching `description`, so the human-readable claim survives even
  when the machine-checkable proof doesn't.
- **`busy_timeout`** is set on every connection; `SQLITE_BUSY` is caught and
  re-raised as a typed error with a clear message, everywhere (CLI exit code
  3, MCP tool error), never an unhandled `sqlite3.OperationalError`.

## 11. KISS trade-offs — what is deliberately not built

| Not built | Why | Upgrade path |
|---|---|---|
| Symbol/AST anchoring | File-level blob hash is 90% of the value (limpet's own README: "thin on purpose") at a fraction of the complexity — no per-language grammars | `ROADMAP.md`, triggered by Phase 4 evidence of excess false-positive `needs_review` |
| Embeddings / vector search | Fixed mission decision; FTS5 BM25 is adequate for the MVP's scale | `ROADMAP.md` |
| Similarity-based rename detection | Exact-hash auto-relink (§5.3) is now built and handles the zero-risk case for free; git's own `-M` heuristic (or any content-diff similarity) is what's excluded — it risks confidently-wrong anchors, the exact failure this project prevents | Documented limitation for the edit-and-move case; manual `record --update-path` |
| Tags table | Type + scope + FTS substitute; nothing in Phase 3 needs more | Add if evidence demands it |
| Auto-merge of duplicates | Mission requires flag-only; destructive summarization is explicitly forbidden | N/A — permanent |
| Instruction-file auto-import | Seeding session (§ Phase 1 gate doc) already answers cold start with the `record` tool the MVP builds anyway | Top `ROADMAP.md` candidate; promoted if Phase 4's cold-start timing exceeds 30 minutes |
| Cached `evidence_strength` | Derived value; caching risks staleness for a cheap-to-compute aggregate | N/A |
| Separate "inspect evidence" MCP tool | Folded into `get_memory` — one fewer tool, same coverage | N/A |
| Multi-writer coordination beyond SQLite locking | Mission fixes single-writer assumption; graceful failure (busy_timeout + clear error) is the whole contract | N/A |
| Gitea webhooks | Mission non-goal; polling/on-demand verify is enough for evidence | N/A |

## 12. Migration mechanism

`PRAGMA user_version` plus ordered, idempotent scripts under `migrations/NNNN_name.sql`.
Runner: read current `user_version`; for each migration file with a version
greater than current, in order, run it inside one transaction, then set
`user_version` to that file's version. Idempotent by construction — a
migration only ever runs once per database because the version check gates
it, so re-running the migrator on an already-current database is a no-op.
`schema.sql` in the repo root is a **readable snapshot** of the current full
schema, kept identical in content to the sum of `migrations/*.sql` — it is
not itself executed. `robo-cortex init` on a brand-new database runs the same
migration chain as an upgrade (there is only one code path for "bring this
database to the current version," whether starting from nothing or from v3);
this is why migrations must be idempotent from empty, not just from an
existing schema. See `schema.sql` (repo root, readable snapshot) for the v1
definition and `src/robo_cortex/migrations/0001_init.sql` for the executed
form — **implementation note added at Stage 3:** the executed migrations live
inside the installed package (`src/robo_cortex/migrations/`), not at the repo
root, so `robo-cortex init` can find and run them from any environment after
`pip install`, not only from a source checkout. The mechanism and ordering
described here are unchanged; only the physical directory moved.
