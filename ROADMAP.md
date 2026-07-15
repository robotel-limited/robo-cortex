# Roadmap

Essential next steps and speculative candidates, explicitly separated. The four
mandatory candidates borrowed from named competitors (`prompt.md`'s deliverable list)
each get a verdict here, graded against the evidence gathered in
[EVALUATION.md](EVALUATION.md) — not taste, per the same anti-self-grading rule the
rest of this project follows.

## Essential next steps (not speculative — concrete, cheap, evidence-backed)

These came directly out of Stage 11's evaluation ([EVALUATION.md](EVALUATION.md) §1,
§4) and are small, low-risk fixes, not new features:

1. **Surface the `assumptions` comma-separator requirement at the point of use.**
   `ARCHITECTURE.md` §5.4 documents it in prose; nothing in `record --help` or
   `MCP_TOOLS.md`'s field description mentions it. Reproduced live in Stage 11: a
   semicolon-joined `assumptions` string silently fails the retrieval gate
   unconditionally, with no error. Fix: one sentence in both surfaces.
2. **A genuine blind cold-start run.** Both cold-start measurements in
   `EVALUATION.md` §7 were performed by the same agent that built (or wrote the
   fixture for) the target repository, so neither independently validates the
   ≤ 30-minute criterion's substance. A separate, unfamiliar agent instance seeding
   a real repository neither implementer has seen is the natural next validation
   step before leaning on that number for anything load-bearing (including the
   instruction-file-import verdict below).
3. **Reconcile `PHASE4_CRITERIA.md`'s Scenario 1 wording with the shipped
   behavior**, or the behavior with the wording: either document that `show` doesn't
   trigger the lazy staleness check (only `retrieve`/`search`/`affected` do), or add
   it as a fourth trigger point if a reviewer decides `show` should refresh staleness
   too. Currently the frozen criteria and the implementation quietly disagree.

## Mandatory candidates (borrowed from named competitors) — verdicts

### 1. Instruction-file auto-import (`CLAUDE.md`/`AGENTS.md` → provisional memories)

**Verdict: not promoted to MVP. Stays on the roadmap, unchanged from the Gate A
decision.**

The Gate A decision (`docs/PHASE1_RESEARCH.md`) named a specific falsification
condition: promote auto-import from roadmap to MVP only if Phase 4's cold-start
measurement shows the manual seeding session (`BOOTSTRAP.md`) blows past 30 minutes
on a realistic fixture. Stage 11 measured cold-start twice
([EVALUATION.md](EVALUATION.md) §7) and neither run produced that evidence — but
neither run is trustworthy enough to be dispositive either way, because both were
performed by an agent already familiar with the target repository. The honest
state is: **the falsification condition was not observed, but the measurement that
would observe it hasn't really been run yet.** This is exactly the "essential next
step" #2 above — until that blind run happens, there is no real evidence pushing
auto-import off the roadmap or onto it, so it stays where Gate A put it: KISS says
prove the simpler mechanism (manual seeding, already built and working per
`BOOTSTRAP.md`) is insufficient before adding a parser, a file-format matrix, and a
second dedup path.

### 2. Symbol-level AST anchoring

**Verdict: not promoted to MVP. Real, now-measured evidence exists, but it argues for
revisiting this candidate with a fuller measurement, not for building it yet.**

`EVALUATION.md` §8 measured, rather than assumed, the spurious-flag rate: **100% of
non-semantic edits tested (5 of 5 — a comment-only addition and a whitespace-only
addition) spuriously flagged every linked memory** `needs_review`, including memories
that had been `active`. This is not a sampling estimate that more data would refine —
it is the deterministic, guaranteed consequence of exact git-blob-hash comparison
(`ARCHITECTURE.md` §5.3): *any* byte-level change to a linked file trips the flag,
full stop, by construction. More samples of "does a comment-only edit flag it" would
not change that number; it is always 100%.

What Stage 11 did **not** measure, and what actually matters for this decision, is the
**naturally-occurring rate** in real project history: what fraction of real commits
touching a memory's linked paths are purely cosmetic (formatting, comments, renames
with no logic change) versus substantive. If that fraction is small in practice (most
real commits to a file also change its behavior), the guaranteed-100%-on-cosmetic-
edits number matters less than it sounds, because cosmetic-only commits are rare. If
it's large (e.g. a codebase with frequent formatter-driven reformatting commits),
false `needs_review` flags could cause real flag fatigue. **This measurement — the
cosmetic-commit fraction across a repository's real git history — is the concrete
next step this candidate needs before a build/no-build call can be made on evidence
rather than intuition.**

Cost side, unchanged from the Gate A analysis: AST anchoring means a per-language
parser investment (limpet's own scope needed 11 language grammars), a real
architectural addition, not a config flag. `implementation-plan.md`'s explicit
rejection of `git diff -w` (whitespace-suppression) as a fix stands regardless of any
future measurement — indentation is semantic in Python, this tool's primary audience
language, so a whitespace-blind diff would trade false positives for false negatives.

### 3. Token-savings accounting (persistent per-repo RETA counter + `stats` surface)

**Verdict: not promoted to MVP. The by-hand measurement built for Stage 11 is
sufficient for now; the persistent counter is not evidenced as necessary.**

Per `docs/TOKEN_ECONOMY_PROTOCOL.md`, this candidate is graded on the Stage 11 numbers
computed by hand, with no new code
([EVALUATION.md](EVALUATION.md) §9). Those numbers: RETA is **negative** (−141
tokens) on a toy fixture with a trivially small linked file, and **strongly positive**
(+6,822 tokens) on real multi-file source — both directions of the proxy's documented
asymmetry, now shown as real numbers rather than a stated caveat. The empirical pilot
(reduced scope, 1 task × 3 runs/arm, agreed with the human reviewer to bound cost)
showed a real but modest effect (median 2.7% fewer tokens, 10.6% less wall-clock),
with an explicit caveat that the chosen task's unusually well-documented codebase
likely compressed the measured effect toward the null.

Building a persistent retrieval-log table and a `stats` command is real schema and
surface-area growth for a number that: (a) can already be computed by hand when
needed, at zero ongoing cost or schema footprint, (b) showed a real but small effect
in the one pilot run so far, and (c) has an admitted, uncorrected asymmetry (it never
counts avoided re-derivation, likely the larger term) that a persistent counter would
not fix — it would just make the same incomplete number easier to accumulate. KISS:
prove the by-hand mechanism insufficient (e.g., a user or agent actually wants
cumulative numbers across many sessions and by-hand computation becomes a real
bottleneck) before building infrastructure for it.

### 4. Editor/statusline integration

**Verdict: roadmap only, no evidence gathered either way — this candidate sits
outside what Stage 11's methodology measures.**

None of the six Gate-B-frozen scenarios, the cold-start measurement, or the
token-economy pilot produced or could have produced evidence relevant to this
candidate — it's an adoption/ergonomics question (does a visible `needs_review` count
or retrieval indicator in an editor status line change how often memories actually
get consulted or kept current?), not a mechanism-correctness question the rest of
this evaluation is built to answer. Recommending for or against it here would be
exactly the taste-based call this project's methodology exists to avoid. If this
becomes a real candidate, it needs its own adoption-focused study (e.g., does usage
of `retrieve`/`search` change measurably with vs. without a visible status-line
indicator), not a retrofit onto Stage 11's existing scenarios.

## Enforcement layers not yet built

`roco hooks install` (v0.3.0) ships a real pre-commit hook: it blocks a commit
touching paths linked to non-terminal memories until they're reviewed, with an
explicit, documented bypass (`git commit --no-verify`). Two more enforcement
layers were described in earlier README drafts before either existed in code
(flagged by an internal audit) — they're real candidates, staying
on the roadmap rather than being built speculatively:

1. **`@requires_memory_check` code decorator.** A Python decorator that queries
   memory before letting a function run. Needs a design decision this project
   hasn't made yet: what does "the check failed" mean at function-call time —
   raise, block, or just log? — and whether it belongs in `robo_cortex.core` at
   all (a decorator is a per-language, per-framework concern; robo-cortex is
   otherwise language-agnostic). Not built until that design question has an
   answer, not just an implementation.
2. **CI/CD merge gate.** `roco affected --diff-range origin/main...HEAD` already
   provides everything a CI job needs to fail a PR touching unreviewed memories
   — see `docs/ci-example.yml` for a copy-paste GitHub Actions job using exactly
   that. What's not built is a packaged, first-class `roco` subcommand for it;
   the existing `affected` command plus a few lines of YAML already cover the
   use case without new surface area. Promote to a dedicated command only if
   the copy-paste version proves insufficient in practice.

## Speculative candidates (implementation-ready, awaiting data)

### 1. Knowledge-base pruning (`robo-cortex prune --older-than-days N`)

**Status: awaiting data accumulation; implementation design complete.**

Usage tracking (`last_used_at`, `use_count` columns in `memory` table) was
added in v0.1.0 to enable data-driven pruning decisions: a `prune` command that
archives or exports memories unused for N days, based on actual retrieval patterns
rather than guess. 

Design is complete but not yet shipped:
- Criteria: `WHERE last_used_at IS NULL OR (NOW() - last_used_at) > N days` 
  (or per-`use_count` thresholds: e.g., "never retrieved, or only once in 6 months")
- UX: `--dry-run` to preview, confirmation prompt, optional backup/export to JSONL
  before actual archival/deletion
- Implementation notes in `src/robo_cortex/core/retrieve.py` `_record_usage()`,
  and minor follow-ups: add `CREATE INDEX idx_memory_last_used_at` when pruning
  queries become real, verify `merge` command exports the new columns in JSONL.

Trigger to build: once 2–3 months of real usage data accumulates, re-evaluate
whether the signal is stable enough to justify a pruning policy.

## Not a candidate, explicitly (already decided, not reopened here)

Embeddings/vector-assisted retrieval, a web UI, multi-user coordination, and cloud
sync are named exclusions in `README.md`'s "what it deliberately does not do" section
and in `ARCHITECTURE.md` — each is an explicit design decision, not a gap awaiting
roadmap evaluation, and nothing in Stage 11's evaluation produced evidence that
reopens any of them.
