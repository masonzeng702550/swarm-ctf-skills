---
description: "Launch a multi-agent swarm attack against a CTF platform. Supports CTFd (login + auto-fetch challenges), Natas (HTTP basic auth chain), and picoCTF (Playwright solver). Solve-count triage, blocker preflight, waved dispatch with lead-driven retries, coordinator-only flag submission."
---

# /swarm-attack — Multi-Agent CTF Campaign (v2)

```
/swarm-attack <platform_url> [--user USER --pass PASS] [--category CAT]
              [--slug EVENT_SLUG] [--max-concurrent N] [--frontier]
```

`--frontier` opts into wave 3 (0-solve challenges). Without it the swarm stops
after wave 2 and reports what remains.

**Doctrine lives in `PLAYBOOK.md` next to this file.** Read it before Step 1.
Every rule below marked `[Ln]` is justified there by a real campaign loss.

## Non-negotiables (Layer 1)

1. **Workers never submit flags.** They report `FLAG: <value>` + derivation.
   The coordinator submits. `[L4]`
2. **Never submit an unverified flag.** A guess costs an attempt and teaches the
   swarm nothing. Max 2 submissions per challenge; if format is ambiguous, ask
   the user. `[L4]`
3. **Max 6 concurrent workers.** `[L7]`
4. Only attack the challenges belonging to this event. No lateral movement into
   platform infrastructure, other teams' instances, or scoreboard tampering.

---

## Step 0 — Project root

`{project_root}` = the directory containing `CLAUDE.md` (cwd at invocation).
`{skill_dir}` = `{project_root}/.claude/skills/swarm-attack`.
All commands below run from `{project_root}`.

## Step 1 — Parse arguments

- `platform_url` — first positional (required)
- `--user` / `--pass` → **CTFd mode**; URL contains `natas` / `picoctf` → see
  Legacy Modes at the bottom
- `--slug` — directory name under `CTF_Records/`; derive from the URL if absent
- `--max-concurrent` — default 6
- `--category`, `--frontier` — optional filters

## Step 2 — Login, fetch, persist

```bash
cd {project_root} && python -c "
import sys, json
sys.path.insert(0, '.')
from core.ctfd_client import CTFdClient

c = CTFdClient('{platform_url}', max_submit_points=10**9)
c.login('{user}', '{pass}')
c.save_session()

detailed = [c.fetch_challenge_detail(ch['id']) for ch in c.fetch_challenges()]
json.dump({
    'platform_url': '{platform_url}',
    'cookie': c.get_cookie_string(),
    'challenges': detailed,
    'solved_ids': [],
}, open('db/campaign.json', 'w'), indent=2, default=str)
print(f'{len(detailed)} challenges fetched')
"
```

**Ethics ceiling.** `max_submit_points` is a hard block inside `submit_flag`.
Its old default (330) silently blocked *every* submission on dynamic-scoring
events where all challenges show 500. Pass a real ceiling only if the user asked
for one; otherwise leave it open and rely on the Layer 1 verification rule.

**Flag format** — never hardcode it. Take it from the event rules page, a solved
challenge, or the description text (`grep -o '[A-Za-z0-9_]*{[^}]*}'`). If it
cannot be determined, ask the user before dispatching; workers grep for it after
every action and a wrong format makes them blind.

Register the campaign:

```bash
cd {project_root} && python tools/memory_cli.py new-campaign \
  --platform "{platform_url}" --team "{user}" --total {n} --slug {event_slug}
```

Capture `campaign_id` from the JSON it prints. Everything downstream tags with it.

## Step 3 — Mint and broadcast the platform intel `[L3]`

Many CTFd events gate per-challenge instancers behind a **CTFd API token**
(`ctfd_<hex>`), not the session cookie. Mint **one** now — workers must never
mint their own, and a second token does not reset a rate limit.

```bash
cd {project_root} && python -c "
import sys, json; sys.path.insert(0,'.')
from core.ctfd_client import CTFdClient
c = CTFdClient('{platform_url}'); c.load_session(); c._refresh_nonce()
r = c._api('POST', '/tokens', json={'description': 'swarm'})
print(json.dumps(r)[:400])
"
```

Broadcast what every worker needs, so nobody rediscovers it:

```bash
cd {project_root} && python tools/memory_cli.py send-message --from coordinator \
  --type platform_info --data '{"flag_format":"{flag_format}","event":"{event_slug}","api_token":"ctfd_...","instancer_note":"lease before use, rate-limited"}'
```

## Step 4 — Blocker preflight (MANDATORY before any spawn) `[L2]`

```bash
cd {project_root} && python3 {skill_dir}/scripts/preflight.py
```

Classifies every remote target as `direct | cf_challenge | auth_required |
instancer | tcp_only | offline` and prints the routing for each class.

- `cf_challenge` → do **not** dispatch a requests/curl worker. Harvest
  `cf_clearance` + UA with `nodriver` under `xvfb-run` (`headless=False`), then
  replay with `curl_cffi(impersonate="chrome131")`. Cookie and UA must match.
- `offline` → report to the user, do not dispatch.
- `instancer` → attach the API token and the lease protocol to that worker's hints.

Record the verdict so wave 2 does not repeat the probe:

```bash
cd {project_root} && python tools/memory_cli.py add-finding \
  --target "{event_slug}:{challenge_name}" --worker coordinator --type partial \
  --data '{"blocker":"cf_challenge","routing":"browser toolkit required"}'
```

## Step 5 — Triage into waves `[L1][L6]`

```bash
cd {project_root} && python3 {skill_dir}/scripts/triage.py --max-concurrent {n}
```

Solve count is the difficulty signal; points are noise under dynamic scoring.
The plan assigns each challenge a tier, a wave, a step budget, a worker name,
and its specialist template:

| Tier | Solves | Wave | Steps | Meaning |
|------|--------|------|-------|---------|
| A | ≥10 | 1 | 14 | harvest — a known trick exists |
| B | 3–9 | 1 | 22 | contested — real work |
| C | 1–2 | 2 | 26 | hard — lead-driven |
| D | 0 | 3 | 30 | frontier — `--frontier` only |

Show the user the plan table before spawning. Wave 3 requires `--frontier`;
otherwise stop after wave 2 and list what was skipped and why `[L11]`.

## Step 6 — Download files, fill templates

```bash
cd {project_root} && python -c "
import sys, json; sys.path.insert(0,'.')
from core.ctfd_client import CTFdClient
c = CTFdClient('{platform_url}'); c.load_session()
print(json.dumps(c.download_challenge_files({challenge_id})))
"
```

Read the `specialist` path from the triage plan and fill:

| Placeholder | Value |
|-------------|-------|
| `{challenge_name}` `{category}` `{points}` `{solves}` `{description}` | from `campaign.json` |
| `{worker_name}` `{max_steps}` | from the triage plan (per-tier budget) |
| `{target_url}` `{cookie}` `{flag_format}` `{challenge_files}` | from campaign + downloads |
| `{campaign_id}` `{source_prefix}` | `{event_slug}` |
| `{hints}` | preflight routing + matching Layer-2 rules + `PLAYBOOK.md` lines for this category |
| `{backup_path}` | `CTF_Records/{event_slug}/challenges/{category}/{name}.md` |

Never leave `{points}` / `{category}` empty — empty values are what produced the
useless `(0pts, unknown)` post-mortem last campaign `[L8]`.

## Step 7 — Dispatch in batches `[L7]`

```python
Agent(prompt=filled_template, run_in_background=True, name="{worker_name}")
```

One batch = at most `--max-concurrent` workers. Do not start the next batch
until the current one has drained and its results are recorded.

## Step 8 — Handle results as they land

**Flag reported** — verify the derivation before touching the platform `[L4]`:
the worker must have read it out of the target, decrypted it, or produced it
with a script that runs end to end. "Looks like the format" is not a solve.

```bash
cd {project_root} && python tools/memory_cli.py add-finding \
  --target "{event_slug}:{challenge_name}" --worker "{worker}" --type flag \
  --data '{"flag":"...","challenge":"...","category":"{category}","points":{points}}'

cd {project_root} && python -c "
import sys, json; sys.path.insert(0,'.')
from core.ctfd_client import CTFdClient
c = CTFdClient('{platform_url}'); c.load_session(); c._refresh_nonce()
print(json.dumps(c.submit_flag({challenge_id}, '{flag}')))
"
```

`status` values: `correct` / `incorrect` / `already_solved` / `blocked`
(ethics ceiling) / `limit_reached` (attempts exhausted — stop, investigate).
On `incorrect`, do not retry with a mutated guess: return the challenge to the
worker as a wave-2 lead. Two submissions per challenge is the cap.

**Budget extension** — a worker emitting `REQUEST: budget_extension` with a
concrete verified primitive (confirmed injection point, leaked path, working
parser, reproducible crash) gets `+8` steps, once. Optimism gets nothing `[L6]`.

**Stuck** — record the lead so wave 2 can use it:

```bash
cd {project_root} && python tools/memory_cli.py add-finding \
  --target "{event_slug}:{challenge_name}" --worker "{worker}" --type partial \
  --data '{"status":"stuck","primitive":"<what is proven to work>","tried":["..."],"next":"<the one step that would unblock>","category":"{category}","points":{points}}'
```

**Retry policy `[L5]`** — retries are where the solves come from. Fund them.

- Retry when wave 1 produced a **verified primitive**. Never decide by points.
- The retry worker gets **more** steps than the original and its prompt embeds
  the prior findings verbatim (name it `{worker}b`).
- No third attempt without new external information (user hint, handoff result).

## Step 9 — Verify instrumentation after wave 1 `[L8]`

```bash
cd {project_root} && python3 -c "
import sys; sys.path.insert(0,'.')
from memory.shared import query_findings, get_active_campaign_id
cid = get_active_campaign_id()
bad = [f for f in query_findings(campaign_id=cid, limit=500)
       if not (f.get('content') or {}).get('category')]
print(f'findings missing category: {len(bad)}')
for f in bad[:10]: print('  ', f['target'], f['type'])
"
```

Non-zero means workers are dropping metadata — fix the prompt before wave 2,
not at post-mortem when the data is already lost.

## Step 10 — Close out

Summary table (solved / stuck / blocked / skipped-frontier), then:

```bash
cd {project_root} && python -c "
import sys; sys.path.insert(0,'.')
from memory.shared import update_campaign
update_campaign({campaign_id}, solved={solved}, status='completed')
"

# writeup coverage gate — do NOT close with missing > 0  [L9]
cd {project_root} && python3 -c "
import sys; sys.path.insert(0,'.')
from memory.shared import query_findings, get_active_campaign_id
cid = get_active_campaign_id()
flags = {f['target'] for f in query_findings(finding_type='flag', campaign_id=cid, limit=500)}
ups   = {f['target'] for f in query_findings(finding_type='writeup', campaign_id=cid, limit=500)}
print(f'writeups {len(ups)}/{len(flags)}')
for t in sorted(flags - ups): print('  MISSING', t)
"

cd {project_root} && python tools/trajectory_export.py --campaign-id {campaign_id}
cd {project_root} && python tools/handoff.py --all-stuck --campaign-id {campaign_id}
```

`trajectory_export.py` writes to `CTF_Records/{event_slug}/trajectories/{campaign_id}/`
(`REPORT.md` + `memory_units.jsonl`). Verify there:

```bash
cd {project_root} && python3 -c "
import json, pathlib, os
base = os.environ.get('CTF_RECORDS_BASE', 'CTF_Records')
p = pathlib.Path(base)/'{event_slug}'/'trajectories'/'{campaign_id}'/'memory_units.jsonl'
u = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
print(len(u), 'units;', sum(x['outcome']=='solved' for x in u), 'solved')
print('no trajectory:', [x['challenge'] for x in u if not x.get('trajectory')][:5])
"
```

Missing trajectories mean workers skipped their heartbeat logging — note it for
the user; that prompt needs fixing before the next event.

## Step 11 — Write RESUME.md

Multi-day events get paused. Write `CTF_Records/{event_slug}/RESUME.md` with:
live score/place/solves, per-challenge **leads with the exact next step**, file
map (`downloads/`, `scratch/`, `writeups/`), the session-refresh snippet, and
the submission snippet. Last campaign's hand-written RESUME.md was what made
day 2 productive — generate it instead of relying on someone remembering.

## Step 12 — Promote lessons into rules

For anything that cost more than one worker, write a Layer 2 rule so the next
campaign starts ahead:

```bash
cd {project_root} && python tools/memory_cli.py add-rule \
  --condition '{"blocker":"cloudflare_managed_challenge"}' \
  --action "nodriver_harvest_clearance_then_curl_cffi_replay"
```

If the lesson is strategic rather than tactical, append it to `PLAYBOOK.md` with
its evidence line. A rule without evidence gets ignored by the next coordinator.

---

## Legacy Mode: Natas

Read `prompts/worker.md`. Levels chain via HTTP basic auth (`natasN` / password
from the previous level); pass credentials through shared-memory findings.

## Legacy Mode: picoCTF

`solver/framework.py` (Playwright) manages instances;
`PUT /api/challenges/ID/instance/` launches them. Check Layer 2 rules first —
29+ patterns are already recorded. Sync results via `solver/swarm_bridge.py`.

## Notes

- All commands run from the project root; findings are shared through
  `memory/shared.py` (SQLite).
- `CTF_RECORDS_BASE` overrides where `CTF_Records/` lives.
- Workers are autonomous within their specialist prompt, budget, and the Layer 1
  rules at the top of this file.
