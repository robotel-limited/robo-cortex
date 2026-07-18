# HAIKU-0 — token-economy benchmark results

**Date:** 2026-07-18 · **Subject model:** Claude Haiku 4.5 (via Claude Code
headless, `claude -p --output-format json`) ·
**Harness:** [scripts/benchmark/](../scripts/benchmark/) · **Raw data:**
[benchmark-results-20260718/](../benchmark-results-20260718/) ·
**Supersedes** the n=3 pilot in [EVALUATION.md §9b](../EVALUATION.md) as the
primary token-economy measurement.

## Design in one paragraph

Three real, historical bugs from this repository's own history were
re-introduced on a fixed HEAD by reverting their fixes (deterministic patches,
3 failing acceptance tests each). Each bug was solved 10× by Haiku 4.5 in an
isolated clone: 5 runs with only a user-style bug report (**baseline**), 5 runs
that additionally received, verbatim, the JSON pack produced by
`roco retrieve` against a store holding the principled lesson recorded about
that fix (**assisted**). Arms were interleaved; the harness re-ran the full
acceptance suite itself after every session (never trusting the agent's
claim) and captured harness-reported usage. Sessions never saw the benchmark
scripts or patches.

## Headline result

**30/30 sessions produced a correct fix** (zero quality disqualifications in
either arm — the honesty clause never fired). Medians of 5 runs/arm:

| task | metric basis | baseline | assisted | saving |
|---|---|---|---|---|
| a1 reverify-on-activate | fresh tokens | 34,703 | 31,060 | **−10.5%** |
| a2 comment-only-reanchor | fresh tokens | 34,764 | 30,624 | **−11.9%** |
| a3 empty-repo-clean-errors | fresh tokens | 53,340 | 39,643 | **−25.7%** |

Paired aggregate (median of per-task % deltas, baseline − assisted):

- **fresh tokens** (input + cache-write + output): **−11.9%**
- **total processed** (incl. cache reads): **−23.5%**
- **API-equivalent cost:** **−15.1%** (per task: −11.2%, −15.1%, −38.7%)
- **turns:** −17.6%
- **wall-clock:** −9.5% — but heterogeneous (**+8.1%** on a1, −9.5% on a2,
  −26.8% on a3); wall-clock is dominated by pytest runs (~37 s each) and API
  latency, and is the noisiest metric here, as in the §9b pilot.

Full per-arm tables: [aggregate.md](../benchmark-results-20260718/aggregate.md).

## Recording cost and break-even K* (Î3, measured — not estimated)

Three separate metered Haiku sessions each recorded one lesson via the roco
CLI (`record` + `activate` + verification `retrieve`) in a fresh clone:

| lesson | fresh tokens | cost $ | wall | K* (fresh) | K* (cost) |
|---|---|---|---|---|---|
| a1 | 17,776 | 0.0596 | 39 s | 4.9 | 5.0 |
| a2 | 25,350 | 0.0825 | 50 s | 6.1 | 4.9 |
| a3 | 16,452 | 0.0559 | 41 s | 1.2 | 0.6 |

**Break-even: a memory pays for itself after ~1–6 sessions that reuse it
(median ≈ 5).** These are upper bounds: the metering sessions started cold,
whereas real recording happens in a session that already holds the context of
the fix it is recording.

Metering footnote: 2 of 3 recording sessions verifiably wrote an active,
repo-scoped memory into their clone's store. The a1 session recorded a correct
lesson but into the **parent repository's** store (the clone lived inside the
parent's directory tree) — a genuine roco UX finding about nested-repo store
resolution, tracked separately.

## Interpretation, honestly stated

1. **The effect is real on Haiku and 4–5× larger than the pilot's** 2.7%
   (Sonnet-class subject, EVALUATION.md §9b) — consistent with the
   "memory helps smaller models more" hypothesis, **not** a replication of the
   pilot (different subject model and tokenizer; only within-experiment
   comparisons are valid).
2. **The effect scales with how hard the answer is to find unaided.** a3
   (multi-file fix: git.py guard + init warning + CLI catch-all) saved 26–39%;
   a1/a2, where failing tests point close to the fix site, saved 10–15%.
3. **Interim reversals were noise.** At n=2, a2 showed assisted *worse* by 7%;
   at n=5 it settled at −12%. Small-n snapshots of this benchmark mislead in
   both directions — the pilot's core caveat, demonstrated live.
4. **No time-savings claim.** Wall-clock differences are within noise on 2 of
   3 tasks.
5. **Limits:** one subject model (small), one codebase (well-documented,
   self-explanatory — likely compresses the effect), 3 tasks, 5 runs/arm,
   memories written at controlled altitude by the orchestrator. Source-B
   (poorly documented third-party codebase) and pilot-model tiers remain
   future work per the plan.

## Verification trail

- 30/30 run dirs contain `result.json`, `fix.diff`, `prompt.txt` (no missing
  logs — the anti-"Faza 7" gate).
- No session modified anything under `tests/` (checked across all 30 diffs).
- Acceptance = full suite green (`--deselect tests/test_smoke.py::test_version_is_set`,
  a pre-existing HEAD inconsistency fixed separately) — re-run by the harness
  in every clone with `PYTHONPATH` pinned to the clone's `src/`.
