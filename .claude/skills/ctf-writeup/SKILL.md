---
description: "Generate a standardized submission-style CTF writeup for a solved challenge. Use after solving (auto-invoked by specialists on FLAG_FOUND) or manually via /ctf-writeup <challenge_name> for a retroactive polish."
---

# /ctf-writeup — Standardised CTF Writeup Generator

Invocation:
```
/ctf-writeup <challenge_name>
/ctf-writeup --all              # regenerate writeups for every flagged challenge in active campaign
```

## Why

Past competitions had a recurring failure: **flag found, then no writeup written**. Two days later the team forgets the trick, and the trajectory log alone is too noisy to recover the solve. This skill closes that gap — every flag triggers a short, standardised writeup that a teammate can validate in 60 seconds.

Specialists call this skill automatically from their `When FLAG Found` block. The user can also run it manually to clean up an old solve.

## Output Path

Writeups live alongside the campaign artifacts:

```
CTF_Records/<event_slug>/writeups/<challenge_name>.md
```

Use `core/records_path.py::active_event_dir(ensure=True)` to resolve the path — it auto-creates the directory.

## Step 1: Resolve Challenge Metadata

For the challenge name supplied:

```bash
python3 - <<'PY'
import json, sys
sys.path.insert(0, '.')
from memory.shared import query_findings, get_active_campaign_id

cid = get_active_campaign_id()
ch_name = "{challenge_name}"

# Fetch the matching flag finding (most recent)
findings = query_findings(finding_type="flag", campaign_id=cid, limit=500)
match = next((f for f in findings if ch_name.lower() in f.get("target", "").lower()), None)
if not match:
    print(f"NO_FLAG_FOR: {ch_name}", file=sys.stderr); sys.exit(1)

print(json.dumps(match, indent=2))
PY
```

Pull from the finding:
- `flag` (the actual string)
- `category`, `points`, `solves` (challenge metadata)
- `worker` (who solved)
- `solved_at` timestamp

## Step 2: Gather Solve Artifacts

```bash
EVENT=$(python3 -c "from core.records_path import active_event_slug; print(active_event_slug() or '')")
WRITEUPS=$(python3 -c "from core.records_path import active_event_dir; p=active_event_dir(ensure=True); print(p / 'writeups' if p else '')")
SCRATCH=$(python3 -c "from core.records_path import active_event_dir; p=active_event_dir(); print(p / 'scratch' if p else '')")

# 1. Find solve scripts the worker created during the run
find "$SCRATCH" -name "*{challenge_slug}*" -name "*.py" -o -name "*{challenge_slug}*" -name "*.sh" 2>/dev/null

# 2. Pull the worker's heartbeat trail (the running log of what they tried)
python3 tools/memory_cli.py heartbeats --challenge "{challenge_name}" --limit 20

# 3. References the worker actually Read (from heartbeat actions)
#    — these become the "Tools / Techniques used" line in the writeup
```

## Step 3: Apply the Submission Template

Write to `$WRITEUPS/<challenge_slug>.md`:

```markdown
---
title: "<Challenge Name>"
ctf: "<event_slug>"
date: YYYY-MM-DD
category: web|pwn|crypto|reverse|forensics|osint|malware|misc
difficulty: <derived from points: easy <100, medium 100-300, hard >300>
points: <number>
flag_format: "<flag_format>"
author: "<worker name>"
references_used:
  - references/<cat>/<file>.md
---

# <Challenge Name>

## Summary

<1-2 sentences: what the challenge was and the core technique. Be direct, no fluff.>

## Solution

### Step 1: Recon / Identification

<3-8 lines: what made the vulnerability obvious — the moment of recognition.>

### Step 2: Exploit (one complete script)

\`\`\`python
# Self-contained script: from challenge data to printed flag.
# No partial snippets — a teammate must be able to copy-paste-run.
<the actual solve script>
\`\`\`

### Step 3: Verification (optional)

<Output of running the script, truncated. Proves the flag is real.>

## Flag

\`\`\`
<the actual flag>
\`\`\`

## Lessons Learned

<1-3 bullets — what to remember next time. This is the part the team re-reads before the next CTF.>
```

## Step 4: Commit to Memory

After writing the file, log it as a finding so `swarm-status` can show writeup coverage:

```bash
python3 tools/memory_cli.py add-finding \
  --target "{event_slug}:{challenge_name}" \
  --worker "ctf-writeup" \
  --type writeup \
  --data '{"path":"<writeup_path>","challenge":"{challenge_name}"}'
```

## Quality Checklist (before saving)

- [ ] **Frontmatter complete** — every YAML field filled
- [ ] **Flag is real** — not a placeholder `flag{...}` literal
- [ ] **Script is self-contained** — runs from challenge data to flag print, no missing imports
- [ ] **Length stays under 200 lines** — including the script. Cut prose, not code.
- [ ] **Reference cited** — if a `references/<cat>/*.md` Pattern was used, list it under `references_used`
- [ ] **No dead ends** — only the path that worked. Pivots only if they explain a key insight.
- [ ] **Lessons Learned filled** — this is the future-self payoff

## Auto-invocation by Specialists

Specialists call this skill from their `When FLAG Found` block — the worker stays in its own context and writes the writeup directly using the embedded template (no actual `/ctf-writeup` call, since sub-agents cannot invoke slash commands). The skill file here is the **canonical template + workflow** that specialists embed.

When the user runs `/ctf-writeup` manually, that re-applies this template against the latest flag finding for the named challenge — useful for retroactively polishing a sloppy auto-writeup.

## Batch mode (`--all`)

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from memory.shared import query_findings, get_active_campaign_id
cid = get_active_campaign_id()
flags = query_findings(finding_type="flag", campaign_id=cid, limit=500)
writeups = query_findings(finding_type="writeup", campaign_id=cid, limit=500)
have = {w["target"] for w in writeups}
missing = [f for f in flags if f["target"] not in have]
for f in missing:
    print(f["target"])
PY
```

Then loop the slash command (or just have the user run it once per challenge).
