---
description: "Display the current swarm campaign dashboard — platform status, per-category progress, recent flags, and ethics-blocked challenges from the shared SQLite database and campaign.json."
---

# /swarm-status — Campaign Status Dashboard

When the user types `/swarm-status`, display a comprehensive campaign dashboard.

## Step 1: Check for Active Campaign

```bash
cd {project_root} && python -c "
import sys, json, os
sys.path.insert(0, '.')

# Check campaign.json
if not os.path.exists('db/campaign.json'):
    print('NO_CAMPAIGN')
else:
    data = json.load(open('db/campaign.json'))
    print(json.dumps({
        'platform_url': data.get('platform_url', 'unknown'),
        'total': len(data.get('challenges', [])),
        'max_submit_points': data.get('max_submit_points', 330),
        'flag_format': data.get('flag_format', 'unknown')
    }))
"
```

If output is `NO_CAMPAIGN`, display:
```
No campaign data found. Use /swarm-attack to start a new campaign.
```
Then stop.

## Step 2: Query Findings from SQLite

```bash
cd {project_root} && python -c "
import sys, json
sys.path.insert(0, '.')
from memory.shared import query_findings, get_active_campaign

# Get campaign info
campaign = get_active_campaign()

# Get all flag findings
flags = query_findings(finding_type='flag', limit=200)

# Separate submitted vs blocked
submitted = [f for f in flags if f.get('content', {}).get('submitted', False)]
blocked = [f for f in flags if not f.get('content', {}).get('submitted', False) and f.get('content', {}).get('status') == 'blocked']

print(json.dumps({
    'campaign': campaign,
    'flags': flags,
    'submitted_count': len(submitted),
    'blocked_count': len(blocked)
}, default=str))
"
```

## Step 3: Load Challenge Data and Compute Per-Category Stats

```bash
cd {project_root} && python -c "
import sys, json
sys.path.insert(0, '.')

data = json.load(open('db/campaign.json'))
challenges = data.get('challenges', [])

# Group by category
from collections import defaultdict
cats = defaultdict(lambda: {'total': 0, 'solved': 0, 'points_total': 0, 'points_solved': 0})
for ch in challenges:
    cat = ch.get('category', 'Misc')
    cats[cat]['total'] += 1
    cats[cat]['points_total'] += ch.get('value', 0)
    if ch.get('solved_by_me'):
        cats[cat]['solved'] += 1
        cats[cat]['points_solved'] += ch.get('value', 0)

# Also check findings DB for flags we found (even if not yet reflected in API)
from memory.shared import query_findings
flags = query_findings(finding_type='flag', limit=200)
solved_names = set(f['target'] for f in flags if f.get('content', {}).get('flag'))

for ch in challenges:
    if ch.get('name') in solved_names and not ch.get('solved_by_me'):
        cat = ch.get('category', 'Misc')
        cats[cat]['solved'] += 1
        cats[cat]['points_solved'] += ch.get('value', 0)

print(json.dumps(dict(cats)))
"
```

## Step 4: Query Recent Flags

```bash
cd {project_root} && python -c "
import sys, json
sys.path.insert(0, '.')
from memory.shared import query_findings

flags = query_findings(finding_type='flag', limit=10)
for f in flags:
    c = f.get('content', {})
    worker = f.get('worker', '?')
    target = f.get('target', '?')
    flag = c.get('flag', '?')
    status = c.get('status', '?')
    print(f'[{worker}]  {target} -> {flag}  ({status})')
"
```

## Step 5: Check Ethics-Blocked Flags

```bash
cd {project_root} && python -c "
import sys, json, os
sys.path.insert(0, '.')

blocked_path = 'db/blocked_flags.jsonl'
if os.path.exists(blocked_path):
    with open(blocked_path) as f:
        for line in f:
            entry = json.loads(line.strip())
            cid = entry.get('challenge_id', '?')
            flag = entry.get('flag', '?')
            print(f'  Challenge {cid} -> {flag} (blocked by ethics rule)')
else:
    print('  (none)')
"
```

## Step 5.4: Retry Candidates and Blockers (the actionable half of this dashboard)

Retries seeded with a verified primitive are where most solves come from, so
surface them first — a primitive sitting unused in SQLite is a wasted solve.

```bash
cd {project_root} && python3 -c "
import sys, json; sys.path.insert(0, '.')
from memory.shared import query_findings, get_active_campaign_id
cid = get_active_campaign_id()
solved = {f['target'] for f in query_findings(finding_type='flag', campaign_id=cid, limit=500)}
ready, blocked = [], []
for f in query_findings(finding_type='partial', campaign_id=cid, limit=500):
    if f['target'] in solved:
        continue
    c = f.get('content') or {}
    if c.get('blocker'):
        blocked.append((f['target'], c['blocker'], c.get('routing', '')))
    elif c.get('primitive') not in (None, 'null', ''):
        ready.append((f['target'], f.get('worker'), c['primitive'], c.get('next', '?')))
print(json.dumps({'retry_ready': ready, 'blocked': blocked}, ensure_ascii=False, indent=1))
"
```

## Step 5.45: Writeup Coverage

```bash
cd {project_root} && python3 -c "
import sys; sys.path.insert(0, '.')
from memory.shared import query_findings, get_active_campaign_id
cid = get_active_campaign_id()
flags = {f['target'] for f in query_findings(finding_type='flag', campaign_id=cid, limit=500)}
ups   = {f['target'] for f in query_findings(finding_type='writeup', campaign_id=cid, limit=500)}
print(f'{len(ups)}/{len(flags)}', 'MISSING:', sorted(flags - ups) or 'none')
"
```

## Step 5.5: Query Performance Metrics

```bash
cd {project_root} && python -c "
import sys, json; sys.path.insert(0, '.')
from memory.shared import get_metrics_summary
summary = get_metrics_summary()
print(json.dumps(summary, indent=2, default=str))
"
```

## Step 6: Display ASCII Dashboard

Combine all data into this format:

```
══════════════════════════════════════════
  AI SWARM — Campaign Dashboard
══════════════════════════════════════════
  Platform: {url}
  Solved: {n}/{total}    Score: {pts} pts

  BY CATEGORY
  ──────────
  Web       (3/7)   ████████░░░   210/450 pts
  Crypto    (2/5)   ████████░░░   200/500 pts
  PWN       (1/4)   ████░░░░░░░   100/400 pts
  Forensics (2/3)   ██████████░   250/300 pts
  Rev       (0/2)   ░░░░░░░░░░░     0/350 pts
  Misc      (1/2)   ██████░░░░░   100/150 pts

  RECENT FLAGS
  ────────────
  [web-1]   Challenge A  ->  RS{flag_here}     (correct)
  [pwn-2]   Challenge B  ->  RS{another}       (correct)
  [crypto-1] Challenge C ->  RS{crypto_flag}   (correct)

  RETRY READY  (verified primitive, no worker on it)
  ───────────────────────────────────────────────────
  Challenge F  [web-1]  SQLi confirmed on /image?id=
                        next: dump /app/.svn/wc.db
  Challenge G  [rev-2]  opcode XOR formula confirmed
                        next: read jump table at VA 0x140024770

  BLOCKED (environmental — route, do not retry)
  ─────────────────────────────────────────────
  Challenge H  cf_challenge   -> browser toolkit (nodriver + curl_cffi)
  Challenge I  instancer      -> needs ctfd_ API token + lease
  Challenge J  offline        -> target down, tell the user

  BLOCKED (ethics)
  ────────────────
  Challenge D (450pts) -> flag recorded but not submitted

  (or "(none)" if no blocked flags)

  WRITEUPS
  ────────
  8/8 covered      (campaign must not close below 100%)

  PERFORMANCE
  ───────────
  Rule accuracy : 78% (14 hits / 18 total)
  Avg solve time: Web 45s, Crypto 120s, PWN 90s
  Worker steps  : web-1 avg 8/15, crypto-1 avg 12/15

  (query via: python tools/memory_cli.py metrics-summary)
══════════════════════════════════════════
```

### Progress Bar Rendering

For each category, render a progress bar with 11 characters:
- Filled blocks: `█` — proportional to solved/total ratio
- Empty blocks: `░` — remaining

Example: 3/7 solved → `████░░░░░░░` (4 filled, 7 empty out of 11)

Formula: `filled = round(solved / total * 11)`

### Adapt to Actual Data

- If no flags found yet, show "No flags captured yet." under RECENT FLAGS
- If no blocked flags, show "(none)" under BLOCKED
- Sort categories by total challenge count descending
- Only show categories that have at least 1 challenge
