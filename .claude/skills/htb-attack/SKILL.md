---
description: "Solve an HTB (Hack The Box) machine. Runs parallel recon workers, then coordinator-dispatched initial-access and privesc specialists. Reports user.txt and root.txt flags for manual submission."
---

# /htb-attack — Multi-Phase HTB Box Solver

Invocation:
```
/htb-attack <TARGET_IP> [--hostname HOSTNAME] [--os linux|windows]
```

---

## Differences vs /swarm-attack

| 面向 | /swarm-attack (CTFd) | /htb-attack |
|------|----------------------|-------------|
| 目標結構 | 平台 API 回傳 N 道獨立題目 | 單台機器，兩個 flag |
| 發現方式 | 直接拉 challenge list | **Recon 是第一個 phase** |
| Flag 格式 | 平台自訂（RS{...}） | 32 hex，固定路徑 |
| 提交方式 | ctfd_client.py 自動提交 | **使用者手動在 HTB 網站提交** |
| 工作流程 | 全部 challenge 並行 | **Phase gate**：recon → initial access → user flag → privesc → root flag |
| 步驟上限 | 每題 15 步 | recon=20、initial_access=35、privesc=35 |

---

## Step 0: Resolve Project Root & Parse Args

Set `{project_root}` = directory containing CLAUDE.md.

Parse:
- `target_ip` — required positional (e.g. `10.129.42.161`)
- `--hostname` — optional (e.g. `example.htb`). If omitted, derive as first word of nmap PTR or leave empty
- `--os` — `linux` (default) or `windows`

Set:
```
{work_dir} = /tmp/htb_{target_ip}
{event_slug} = htb-{target_ip_dashed}   (e.g. htb-10-129-42-161)
```

---

## Step 1: Setup

```bash
mkdir -p {work_dir}

# /etc/hosts — IMPORTANT: vhosts won't resolve without this
# Check if already present; if not, remind user:
grep -q "{target_ip}" /etc/hosts 2>/dev/null || \
  echo "[ACTION REQUIRED] Add to /etc/hosts: {target_ip} {hostname}"
# Try automatic addition (requires sudo):
grep -q "{target_ip}" /etc/hosts 2>/dev/null || \
  echo "{target_ip} {hostname}" | sudo tee -a /etc/hosts 2>/dev/null || \
  echo "[INFO] Could not auto-add /etc/hosts — add manually: {target_ip} {hostname}"
```

Initialize campaign in SQLite:
```bash
cd {project_root} && python tools/memory_cli.py new-campaign \
  --platform "htb" --team "attacker" --total 2 \
  --slug "{event_slug}" 2>/dev/null
# Capture campaign_id from output
```

Check Layer 2 rules for any matching prior HTB learnings:
```bash
cd {project_root} && python tools/memory_cli.py list-rules --status active 2>/dev/null | \
  grep -i "htb\|linux\|privesc\|web\|docker\|ssh" | head -20
```

---

## Step 2: Parallel Recon (3 workers, run_in_background=True)

Read `prompts/specialists/htb_recon.md`. Dispatch **3 simultaneous workers**, each with a different role:

| Worker name | {recon_role} | Focus |
|-------------|--------------|-------|
| `recon-ports` | `PORT_SCAN` | nmap full TCP/UDP |
| `recon-web`   | `WEB_ENUM`  | vhost fuzz, path fuzz, tech stack |
| `recon-osint` | `OSINT_TECH` | TLS SANs, sensitive files, banners |

Fill template placeholders:

| Placeholder | Value |
|-------------|-------|
| `{target_ip}` | parsed target IP |
| `{hostname}` | parsed hostname or `{target_ip}` |
| `{recon_role}` | role letter (A/B/C) + name |
| `{work_dir}` | `/tmp/htb_{target_ip}` |
| `{project_root}` | resolved project root |

```python
Agent(prompt=filled_recon_template, run_in_background=True, name="recon-ports")
Agent(prompt=filled_recon_template, run_in_background=True, name="recon-web")
Agent(prompt=filled_recon_template, run_in_background=True, name="recon-osint")
```

**Wait for ALL 3 recon workers to complete** before proceeding.

---

## Step 3: Coordinator Analysis — Read Recon, Rank Attack Vectors

After workers complete, parse their structured `=== RECON RESULT ===` blocks.

Merge into a unified summary:
```bash
cat {work_dir}/nmap_full.txt 2>/dev/null
ls {work_dir}/vhosts*.json 2>/dev/null | xargs cat 2>/dev/null
ls {work_dir}/paths*.json 2>/dev/null | xargs cat 2>/dev/null
```

Build an **attack vector table** ranked by priority. Examples:

| Priority | Vector ID | Description | Why |
|----------|-----------|-------------|-----|
| HIGH | `web-ssrf-mcp` | MCPJam /api/mcp/connect SSRF | Accepts arbitrary URL server-side |
| HIGH | `web-rce-flowise` | Flowise 3.0.5 customFunction RCE | Known version with unauth RCE |
| MEDIUM | `creds-default` | Default credential spray on all services | Admin:admin, app-name as pass |
| LOW | `ssh-bruteforce` | SSH password brute force | No username yet |

**Rules for prioritization:**
- Services with known CVEs for the detected version → HIGH
- Endpoints that accept user-controlled URLs (SSRF) → HIGH
- World-writable system binaries → HIGH (instant privesc once shell)
- Default credentials on any detected service → HIGH
- SSH/FTP with password auth + no known usernames → LOW

**Select top 2 vectors** to run in parallel as initial-access workers.

Display analysis to user:
```
[HTB COORDINATOR] Recon complete. Attack surface:

Open ports:   22 (SSH), 80 (HTTP→HTTPS), 443 (HTTPS)
Vhosts:       bin.example.htb (PrivateBin 2.0.2), mcp.example.htb (MCPJam)
Interesting:  MCPJam SSRF candidate, PrivateBin world-writable PHP file

Dispatching 2 initial-access workers:
  [ia-1] web-ssrf-mcp   → MCPJam SSRF → internal RCE
  [ia-2] creds-default  → credential spray across Flowise/Gogs/admin panels
```

---

## Step 4: Parallel Initial Access (max 2 workers, run_in_background=True)

Read `prompts/specialists/htb_initial_access.md`. Fill placeholders:

| Placeholder | Value |
|-------------|-------|
| `{target_ip}` | target IP |
| `{hostname}` | target hostname |
| `{vector_id}` | from attack vector table |
| `{vector_description}` | one-line description |
| `{vector_priority}` | HIGH/MEDIUM/LOW |
| `{vector_difficulty}` | estimated 1-5 |
| `{recon_summary}` | merged recon output (key facts only, max 30 lines) |
| `{known_creds}` | from SQLite findings, or "none" |
| `{work_dir}` | `/tmp/htb_{target_ip}` |
| `{project_root}` | project root |
| `{worker_name}` | `ia-1`, `ia-2` |
| `{campaign_id}` | from Step 1 |

```python
Agent(prompt=filled_ia_template_1, run_in_background=True, name="ia-1")
Agent(prompt=filled_ia_template_2, run_in_background=True, name="ia-2")
```

### Process results as they come in

Parse `=== INITIAL ACCESS RESULT ===` blocks.

**If `STATUS: SHELL_OBTAINED`:**
1. Store shell info to SQLite immediately (add-finding type=shell)
2. Store any found credentials immediately
3. Check if `USER_FLAG:` is in the output → record and display
4. Cancel/ignore remaining ia- workers (shell obtained)
5. Proceed to **Step 5**

**If `STATUS: STUCK`:**
- Record partial intel (add-finding type=partial)
- If both workers stuck, try next-priority vector from the attack table
- If all top-3 vectors exhausted: pause and report to user with detailed stuck summary

---

## Step 5: User Flag Collection

If worker already found user.txt → skip. Otherwise:

```bash
# With the obtained shell (replace with actual shell method):
# Try reading common user flag locations
cat /home/*/user.txt 2>/dev/null
find /home -name "user.txt" 2>/dev/null | xargs cat 2>/dev/null
```

Record immediately:
```bash
cd {project_root} && python tools/memory_cli.py add-finding \
  --target "htb:{target_ip}" \
  --worker "coordinator" \
  --type flag \
  --data '{"flag":"{USER_FLAG}","type":"user","path":"/home/{USER}/user.txt"}'
```

Display to user:
```
[HTB] USER FLAG: {user_flag}
      Path: /home/{user}/user.txt
      → Submit at: https://www.hackthebox.com/achievement/machine/...
```

---

## Step 6: Parallel Privesc (max 2 workers, run_in_background=True)

Collect shell context to pass to workers:
```bash
# Run via existing shell:
id; whoami; hostname; uname -a; cat /etc/os-release; ip addr
sudo -l 2>/dev/null
find / -perm /4000 2>/dev/null | grep -v proc | grep -v sys | head -20
find /usr/bin /bin -writable 2>/dev/null
ps aux | grep root | grep -v "\["
ss -tlnp 2>/dev/null | grep LISTEN
```

Read `prompts/specialists/htb_privesc.md`. Fill placeholders:

| Placeholder | Value |
|-------------|-------|
| `{target_ip}` | target |
| `{current_user}` | shell username |
| `{current_uid}` | shell UID |
| `{shell_info}` | output of id/uname/ps collection above |
| `{reconnect_cmd}` | exact command to reconnect (ssh/curl/etc.) |
| `{known_creds}` | all found creds from SQLite |
| `{work_dir}` | work dir |
| `{project_root}` | project root |
| `{worker_name}` | `pe-1`, `pe-2` |

Dispatch **2 workers** targeting different privesc angles:
- `pe-1`: quick wins (SUID, sudo, writable binaries, cron)
- `pe-2`: service/container escalation (docker socket, management APIs, credential reuse)

```python
Agent(prompt=filled_pe_template_1, run_in_background=True, name="pe-1")
Agent(prompt=filled_pe_template_2, run_in_background=True, name="pe-2")
```

### Process results as they come in

**If `STATUS: ROOT_FLAG value=<hex>`:**
1. Record to SQLite (add-finding type=flag)
2. Display immediately
3. Cancel remaining pe- workers

**If `STATUS: STUCK`:**
- Record partial intel
- Try next-priority privesc approach
- If 3 approaches exhausted: report to user with full enumeration findings

---

## Step 7: Root Flag & Final Summary

Display:
```
╔══════════════════════════════════════════════╗
║         HTB — {hostname} — PWNED             ║
╠══════════════════════════════════════════════╣
║  Target   : {target_ip} ({hostname})         ║
║  Duration : {elapsed}                        ║
╠══════════════════════════════════════════════╣
║  USER FLAG  : {user_flag}                    ║
║  ROOT FLAG  : {root_flag}                    ║
╠══════════════════════════════════════════════╣
║  ATTACK CHAIN                                ║
║  1. {step1}                                  ║
║  2. {step2}                                  ║
║  3. {step3}                                  ║
╚══════════════════════════════════════════════╝

Submit flags at: https://www.hackthebox.com
```

Update campaign:
```bash
cd {project_root} && python -c "
import sys; sys.path.insert(0, '.')
from memory.shared import update_campaign
update_campaign({campaign_id}, solved=2, status='completed')
" 2>/dev/null
```

Run post-mortem (same as swarm-attack Step 10):
```bash
cd {project_root} && python tools/trajectory_export.py --campaign-id {campaign_id} 2>/dev/null
```

---

## Step 8: Learn — Auto-generate Layer 2 Rules

After each box, extract reusable patterns and save as rules:

```bash
# Example: if we exploited a world-writable /usr/bin/bash
cd {project_root} && python tools/memory_cli.py add-rule \
  --condition "find /usr/bin /bin -writable finds a common binary (bash, sh, python)" \
  --action "Install backdoor that copies /root/root.txt on root execution; wait for cron/health-check trigger" \
  --confidence 0.9 \
  --tags "htb,linux,privesc,writable_binary"

# Example: MCPJam SSRF pattern
cd {project_root} && python tools/memory_cli.py add-rule \
  --condition "MCPJam Inspector (/api/mcp/connect) present with no auth" \
  --action "Connect to self-hosted malicious MCP server; use tool execution for RCE" \
  --confidence 0.85 \
  --tags "htb,web,ssrf,mcp,rce"
```

---

## Notes

- **Phase gates are mandatory**: never dispatch privesc workers without a confirmed shell
- **Step limits are hard stops**: workers must stop at 35 steps regardless of progress
- **Credentials go to SQLite immediately**: never lose creds to session end
- **/etc/hosts**: add hostname before dispatching recon-web; vhosts will be missed otherwise
- **No flag auto-submission**: HTB requires manual submission at hackthebox.com
- **Windows variant**: if `--os windows`, recon-web adds SMB/WinRM paths; privesc uses `whoami /priv`, `winPEAS`, token impersonation patterns — extend specialist prompts accordingly
