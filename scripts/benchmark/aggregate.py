#!/usr/bin/env python3
"""Aggregate HAIKU-0 benchmark results into a markdown report.

Reads bench-work/runs/*/result.json. Per honesty clause, runs that fail
acceptance are listed but excluded from the savings medians.

Metrics per run:
  fresh_tokens = input + cache_creation + output   (newly processed work)
  total_tokens = fresh + cache_read                (everything the model saw)
  cost_usd     = harness-reported API-equivalent cost (weights cache correctly)
  wall_clock_s, num_turns
"""
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE.parent.parent / "bench-work" / "runs"


def metrics(result: dict) -> dict:
    mu = result["claude"]["modelUsage"] or {}
    fresh = total = 0
    for m in mu.values():
        f = m["inputTokens"] + m["cacheCreationInputTokens"] + m["outputTokens"]
        fresh += f
        total += f + m["cacheReadInputTokens"]
    return {
        "fresh": fresh, "total": total,
        "cost": result["claude"]["total_cost_usd"],
        "wall": result["wall_clock_s"],
        "turns": result["claude"]["num_turns"],
        "pass": result["acceptance_pass"],
    }


def med(rows, key):
    vals = [r[key] for r in rows]
    return statistics.median(vals) if vals else None


def main():
    runs = []
    for rj in sorted(RUNS.glob("*/result.json")):
        r = json.loads(rj.read_text())
        r["_m"] = metrics(r)
        runs.append(r)

    tasks = sorted({r["task"] for r in runs})
    print(f"# HAIKU-0 results — {len(runs)} sessions\n")

    failed = [r for r in runs if not r["_m"]["pass"]]
    print(f"Failed acceptance (excluded from medians): "
          f"{[f'{r['task']}-{r['arm']}-{r['run']}' for r in failed] or 'none'}\n")

    print("| task | arm | n(pass) | med fresh tok | med total tok | "
          "med cost $ | med wall s | med turns |")
    print("|---|---|---|---|---|---|---|---|")
    deltas = {}
    for t in tasks:
        per_arm = {}
        for arm in ("baseline", "assisted"):
            rows = [r["_m"] for r in runs
                    if r["task"] == t and r["arm"] == arm and r["_m"]["pass"]]
            per_arm[arm] = rows
            print(f"| {t} | {arm} | {len(rows)} | {med(rows,'fresh'):.0f} | "
                  f"{med(rows,'total'):.0f} | {med(rows,'cost'):.4f} | "
                  f"{med(rows,'wall'):.0f} | {med(rows,'turns'):.0f} |"
                  if rows else f"| {t} | {arm} | 0 | — | — | — | — | — |")
        b, a = per_arm["baseline"], per_arm["assisted"]
        if b and a:
            deltas[t] = {k: (med(b, k) - med(a, k), med(b, k))
                         for k in ("fresh", "total", "cost", "wall", "turns")}

    print("\n## Delta per task (baseline − assisted, medians; + = assisted saves)\n")
    print("| task | fresh tok | total tok | cost $ | wall s | turns |")
    print("|---|---|---|---|---|---|")
    for t, d in deltas.items():
        cells = []
        for k in ("fresh", "total", "cost", "wall", "turns"):
            diff, base = d[k]
            pct = 100 * diff / base if base else 0
            fmt = f"{diff:+.4f}" if k == "cost" else f"{diff:+.0f}"
            cells.append(f"{fmt} ({pct:+.1f}%)")
        print(f"| {t} | " + " | ".join(cells) + " |")

    if deltas:
        print("\n## Paired aggregate (median of per-task percentage deltas)\n")
        for k in ("fresh", "total", "cost", "wall", "turns"):
            pcts = [100 * d[k][0] / d[k][1] for d in deltas.values() if d[k][1]]
            print(f"- {k}: {statistics.median(pcts):+.1f}%  (per task: "
                  + ", ".join(f"{p:+.1f}%" for p in pcts) + ")")


if __name__ == "__main__":
    main()
