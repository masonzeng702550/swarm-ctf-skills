#!/usr/bin/env python3
"""Turn db/campaign.json into a wave dispatch plan.

Replaces the old "sort by points ascending" heuristic, which is useless on
dynamic-scoring events (every unsolved challenge shows the same maximum point
value, so points carry zero difficulty signal). Solve count is the signal.

Usage:
    python3 .claude/skills/swarm-attack/scripts/triage.py
    python3 .claude/skills/swarm-attack/scripts/triage.py --category web --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# tier -> (min_solves, wave, step_budget, note)
TIERS = [
    ("A", 10, 1, 14, "harvest - many solves, expect a known trick"),
    ("B", 3, 1, 22, "contested - real work, worth full budget"),
    ("C", 1, 2, 26, "hard - at least one team solved it, lead-driven"),
    ("D", 0, 3, 30, "frontier - 0 solves, opt-in only"),
]

# category -> specialist template under prompts/specialists/
SPECIALIST = {
    "web": "web", "web exploitation": "web",
    "pwn": "pwn", "binary exploitation": "pwn",
    "crypto": "crypto", "cryptography": "crypto",
    "rev": "rev", "reverse": "rev", "reversing": "rev",
    "reverse engineering": "rev",
    "forensics": "forensics",
    "osint": "osint",
}


def tier_for(solves: int) -> tuple[str, int, int, str]:
    for name, min_solves, wave, budget, note in TIERS:
        if solves >= min_solves:
            return name, wave, budget, note
    return "D", 3, 30, "frontier"


def specialist_for(category: str) -> str:
    """Which prompts/specialists/<x>.md template handles this category."""
    return SPECIALIST.get((category or "misc").strip().lower(), "misc")


def worker_prefix_for(category: str) -> str:
    """Worker name keeps the platform's own category so the board stays readable
    (a blockchain challenge is 'chain-1', not an anonymous 'misc-7')."""
    raw = (category or "misc").strip().lower().split()[0] if category else "misc"
    return {"blockchain": "chain", "reverse": "rev", "reversing": "rev",
            "cryptography": "crypto", "binary": "pwn"}.get(raw, raw)[:8]


def build_plan(challenges: list[dict], category: str | None, concurrency: int) -> dict:
    rows = []
    for ch in challenges:
        cat = str(ch.get("category") or "misc")
        if category and cat.strip().lower() != category.strip().lower():
            continue
        if ch.get("solved_by_us"):
            continue
        try:
            solves = int(ch.get("solves") or 0)
        except (TypeError, ValueError):
            solves = 0
        try:
            points = int(ch.get("points") or ch.get("value") or 0)
        except (TypeError, ValueError):
            points = 0
        tier, wave, budget, note = tier_for(solves)
        rows.append({
            "id": ch.get("id"),
            "name": ch.get("name"),
            "category": cat,
            "specialist": f"prompts/specialists/{specialist_for(cat)}.md",
            "worker_prefix": worker_prefix_for(cat),
            "solves": solves,
            "points": points,
            "tier": tier,
            "wave": wave,
            "step_budget": budget,
            "rationale": note,
            "has_files": bool(ch.get("files")),
        })

    rows.sort(key=lambda r: (r["wave"], -r["solves"], r["points"]))

    # assign per-category worker names in dispatch order
    counters: dict[str, int] = {}
    for r in rows:
        counters[r["worker_prefix"]] = counters.get(r["worker_prefix"], 0) + 1
        r["worker"] = f"{r['worker_prefix']}-{counters[r['worker_prefix']]}"

    waves: dict[str, list[dict]] = {}
    for r in rows:
        waves.setdefault(f"wave{r['wave']}", []).append(r)

    # batch each wave so we never exceed the concurrency cap
    batches = []
    for wave_name in sorted(waves):
        items = waves[wave_name]
        for i in range(0, len(items), concurrency):
            batches.append({
                "wave": wave_name,
                "batch": len(batches) + 1,
                "workers": [x["worker"] for x in items[i:i + concurrency]],
            })

    dynamic_scoring = len({r["points"] for r in rows if r["solves"] == 0}) <= 1 and len(rows) > 3
    return {
        "total": len(rows),
        "concurrency": concurrency,
        "dynamic_scoring_suspected": dynamic_scoring,
        "tier_counts": {t: sum(1 for r in rows if r["tier"] == t) for t in "ABCD"},
        "challenges": rows,
        "batches": batches,
    }


def render(plan: dict) -> str:
    out = []
    out.append(f"Triage: {plan['total']} unsolved · concurrency cap {plan['concurrency']}")
    tc = plan["tier_counts"]
    out.append(
        f"  A(harvest) {tc['A']}   B(contested) {tc['B']}   "
        f"C(hard) {tc['C']}   D(frontier, opt-in) {tc['D']}"
    )
    if plan["dynamic_scoring_suspected"]:
        out.append("  ! dynamic scoring detected - points are NOT a difficulty signal, solves are")
    out.append("")
    out.append(f"{'W':<3}{'Tier':<6}{'Worker':<12}{'Slv':>4}{'Pts':>6}  {'Category':<12}Challenge")
    out.append("-" * 88)
    for r in plan["challenges"]:
        out.append(
            f"{r['wave']:<3}{r['tier']:<6}{r['worker']:<12}{r['solves']:>4}{r['points']:>6}  "
            f"{r['category'][:11]:<12}{str(r['name'])[:36]}  [{r['step_budget']} steps]"
        )
    out.append("")
    for b in plan["batches"]:
        out.append(f"  {b['wave']} batch {b['batch']}: {', '.join(b['workers'])}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Wave dispatch plan from campaign.json")
    ap.add_argument("--campaign", default="db/campaign.json")
    ap.add_argument("--category", default=None)
    ap.add_argument("--max-concurrent", type=int, default=6)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    path = Path(args.campaign)
    if not path.exists():
        print(f"error: {path} not found - run the login step first", file=sys.stderr)
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    solved_ids = set(data.get("solved_ids") or [])
    challenges = [c for c in data.get("challenges", []) if c.get("id") not in solved_ids]

    plan = build_plan(challenges, args.category, args.max_concurrent)
    print(json.dumps(plan, ensure_ascii=False, indent=2) if args.json else render(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
