# swarm-ctf-skills

[English](README.md) · [繁體中文](README.zh-TW.md)

A multi-agent skill and prompt layer for running CTF campaigns with Claude Code.
A coordinator agent triages a challenge board, dispatches specialist workers in
waves, and enforces the operational rules that keep a swarm from wasting its own
budget.

The design premise is that a swarm usually loses to its own dispatch policy
rather than to the challenges. Most of what follows exists to remove a specific,
observed category of waste.

## What is in this repository

| Layer | Path | Contents |
|---|---|---|
| Skills | `.claude/skills/` | 7 Claude Code skills — campaign orchestration, status dashboard, HTB solver, writeup generator, and three Active Directory tools |
| Prompts | `prompts/` | Coordinator, worker, shared doctrine, and 10 domain specialists |
| Reference library | `references/` | 107 technique files across 9 categories, plus a generated lookup index |

### Skills

| Skill | Purpose |
|---|---|
| `swarm-attack` | Multi-agent CTF campaign against CTFd, Natas, or picoCTF. Solve-count triage, blocker preflight, waved dispatch, coordinator-only flag submission |
| `swarm-status` | Campaign dashboard — per-category progress, recent flags, blocked challenges |
| `htb-attack` | Hack The Box machine solver: parallel recon, then initial-access and privesc specialists |
| `ctf-writeup` | Standardised writeup generation, fired at solve time |
| `ad-preflight` | Windows AD attacker-host readiness checklist (TUN/MTU, krb5.conf, clock sync, port matrix) |
| `gmsa-takeover` | Converts write access on a gMSA's `msDS-GroupMSAMembership` into its NT hash |
| `wsus-mitm` | Rogue WSUS server, ADIDNS spoofing, and Windows Update trigger pipeline |

### Reference library

| Category | Files | Category | Files |
|---|---|---|---|
| web | 20 | forensics | 14 |
| pwn | 18 | misc | 12 |
| reverse | 18 | ai-ml | 3 |
| crypto | 16 | malware | 3 |
| osint | 3 | | |

Workers read `references/INDEX.md` first, match challenge keywords against it,
then read only the one to three files that match. Regenerate the index after
editing any reference file:

```bash
python tools/build_ref_index.py
```

## Operating doctrine

`.claude/skills/swarm-attack/PLAYBOOK.md` holds twelve rules, each derived from
an observed campaign failure. The load-bearing ones:

- **Solve count is the difficulty signal, not points.** Under dynamic scoring
  every unsolved challenge shows the maximum value, so sorting by points sorts
  by noise.
- **Probe the blocker before spending a worker.** Classify targets first
  (`scripts/preflight.py`); a Cloudflare-fronted target will consume a full
  budget from any `requests`-based worker and return nothing.
- **Workers never submit flags.** They report the value and its derivation; the
  coordinator submits, capped at two attempts per challenge.
- **Fund the retry.** Retries seeded with wave-1 findings produce a large share
  of solves, yet budgets are routinely cut across waves. Eligibility is decided
  by lead quality, never by point value.
- **Cap concurrency at six.** Higher concurrency has caused worker evictions and
  silently lost results.

## Requirements

This repository is the **skill, prompt, and reference layer only**. The skills
invoke a campaign runtime that is not included here:

```
tools/memory_cli.py        shared finding/heartbeat store  (referenced ~173x)
tools/cli.py               campaign lifecycle
tools/writeup.py           writeup generation
tools/handoff.py           stuck-challenge handoff
tools/trajectory_export.py post-campaign export
memory/shared.py           query_findings, get_active_campaign_id
core/ctfd_client.py        CTFd session + challenge fetch
core/rctf_client.py        rCTF client
db/campaign.json           per-campaign state
```

Without that runtime the skills will not execute end to end. The prompts,
doctrine, and reference library are useful on their own, and the three scripts
that ship here (`preflight.py`, `triage.py`, `build_ref_index.py`) run
standalone. Skills also expect a `CLAUDE.md` at the project root as the
root marker.

## Scope and intended use

These are offensive-security tools built for CTF competitions, Hack The Box,
and authorised penetration testing. The Active Directory skills
(`gmsa-takeover`, `wsus-mitm`) perform real attacks against real Windows
infrastructure.

Use them only against systems you own or have explicit written authorisation to
test. The `swarm-attack` skill additionally forbids lateral movement into
platform infrastructure, other teams' instances, and scoreboard tampering.

## Attribution

The entire `references/` library is taken from
**[ljagiello/ctf-skills](https://github.com/ljagiello/ctf-skills)** by
Lukasz Jagiello, used under the MIT License. This project reorganises the files
into `references/<category>/` and adds a generated lookup index; no upstream
text was removed or rewritten. `.claude/skills/ctf-writeup/SKILL.md` is also
derived from that project.

That library is the foundation this project's specialists read from, and it is
worth using directly if you do not need the swarm layer.

See [`NOTICE`](NOTICE) for the full attribution and
[`references/LICENSE.ctf-skills`](references/LICENSE.ctf-skills) for the
upstream licence text.

## Licence

Original work in this repository is MIT licensed — see [`LICENSE`](LICENSE).
Third-party material under `references/` remains Copyright (c) 2026
Lukasz Jagiello under the MIT License; see [`NOTICE`](NOTICE).
