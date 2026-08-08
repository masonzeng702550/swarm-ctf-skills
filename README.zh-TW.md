# swarm-ctf-skills

[English](README.md) · [繁體中文](README.zh-TW.md)

搭配 Claude Code 執行 CTF 賽事的多代理 skill 與 prompt 層。由一個 coordinator
代理對題目板進行分流，分波派遣各領域的 specialist worker，並以明確規則約束整個
swarm，避免它把預算浪費在自己的派工決策上。

本專案的設計前提是：**swarm 通常不是輸給題目，而是輸給自己的派工策略。** 以下
多數機制的存在目的，都是消除某一類已被觀察到的具體浪費。

## 內容

| 層 | 路徑 | 內容 |
|---|---|---|
| Skills | `.claude/skills/` | 7 個 Claude Code skill —— 賽事編排、狀態看板、HTB 解題、writeup 產生器，以及三個 Active Directory 工具 |
| Prompts | `prompts/` | coordinator、worker、共用 doctrine，以及 10 個領域 specialist |
| 參考知識庫 | `references/` | 9 個分類共 107 份技術參考檔，附自動產生的查詢索引 |

### Skills

| Skill | 用途 |
|---|---|
| `swarm-attack` | 對 CTFd、Natas、picoCTF 發動多代理賽事。以解題數分流、阻斷器預檢、分波派遣，且僅由 coordinator 提交 flag |
| `swarm-status` | 賽事看板 —— 各分類進度、近期 flag、被擋下的題目 |
| `htb-attack` | Hack The Box 機器解題：先平行偵察，再派遣初始存取與提權 specialist |
| `ctf-writeup` | 標準化 writeup 產生，於解題當下即觸發 |
| `ad-preflight` | Windows AD 攻擊主機整備檢查表（TUN/MTU、krb5.conf、時鐘同步、埠對照表） |
| `gmsa-takeover` | 把 gMSA 的 `msDS-GroupMSAMembership` 寫入權限轉換為該帳號的 NT hash |
| `wsus-mitm` | 惡意 WSUS 伺服器、ADIDNS 欺騙與 Windows Update 觸發管線 |

### 參考知識庫

| 分類 | 檔數 | 分類 | 檔數 |
|---|---|---|---|
| web | 20 | forensics | 14 |
| pwn | 18 | misc | 12 |
| reverse | 18 | ai-ml | 3 |
| crypto | 16 | malware | 3 |
| osint | 3 | | |

Worker 先讀 `references/INDEX.md`，以題目關鍵字比對後，只讀取命中的 1 至 3 份
檔案，而非整個分類。修改任何參考檔後請重新產生索引：

```bash
python tools/build_ref_index.py
```

## 運作準則

`.claude/skills/swarm-attack/PLAYBOOK.md` 收錄 12 條規則，每一條都來自一次實際
觀察到的失敗。其中最關鍵的幾條：

- **難度訊號是解題數，不是分數。** 動態計分下每道未解題都顯示最高分值，因此依
  分數排序等同依雜訊排序。
- **派工前先探測阻斷器。** 先用 `scripts/preflight.py` 分類目標；被 Cloudflare
  擋住的目標會吃掉任何 `requests` 型 worker 的整份預算且毫無產出。
- **Worker 絕不提交 flag。** 它只回報數值與推導過程，由 coordinator 提交，且每
  題上限兩次。
- **要餵飽重試。** 以第一波發現為種子的重試貢獻了相當高比例的解題，但賽事卻常
  在後續波次刪減預算。重試資格由線索品質決定，絕不由分數決定。
- **併發上限為 6。** 更高的併發曾造成 worker 被驅逐、結果無聲遺失。

## 執行需求

本 repo 僅包含 **skill、prompt 與參考知識庫三層**。skill 會呼叫一套並未收錄於此
的賽事執行環境：

```
tools/memory_cli.py        共用的 finding/heartbeat 儲存（被引用約 173 次）
tools/cli.py               賽事生命週期
tools/writeup.py           writeup 產生
tools/handoff.py           卡關題目交接
tools/trajectory_export.py 賽後匯出
memory/shared.py           query_findings、get_active_campaign_id
core/ctfd_client.py        CTFd 登入與題目抓取
core/rctf_client.py        rCTF 客戶端
db/campaign.json           單場賽事狀態
```

缺少該執行環境時，skill 無法端到端運作。但 prompt、運作準則與參考知識庫本身即可
單獨使用，且隨附的三個腳本（`preflight.py`、`triage.py`、`build_ref_index.py`）
可獨立執行。skill 另外預期專案根目錄存在 `CLAUDE.md` 作為根目錄標記。

## 適用範圍

這是為 CTF 競賽、Hack The Box 與**經授權**滲透測試打造的攻擊性資安工具。其中的
Active Directory skill（`gmsa-takeover`、`wsus-mitm`）會對真實 Windows 基礎設施
執行真實攻擊。

請僅對你擁有、或已取得明確書面授權測試的系統使用。`swarm-attack` 另外明文禁止
橫向移動至平台基礎設施、他隊的題目實例，以及任何計分板竄改行為。

## 出處與致謝

`references/` 知識庫全部取自 Lukasz Jagiello 的
**[ljagiello/ctf-skills](https://github.com/ljagiello/ctf-skills)**，依 MIT
授權使用。本專案將檔案重新整理為 `references/<category>/` 結構並加上自動產生的
查詢索引，未刪改任何上游內容。`.claude/skills/ctf-writeup/SKILL.md` 同樣衍生自
該專案。

該知識庫是本專案各 specialist 的知識來源；若你不需要 swarm 這一層，直接使用上游
專案是更好的選擇。

完整出處說明見 [`NOTICE`](NOTICE)，上游授權原文見
[`references/LICENSE.ctf-skills`](references/LICENSE.ctf-skills)。

## 授權

本 repo 的原創部分以 MIT 授權釋出，見 [`LICENSE`](LICENSE)。`references/` 之下
的第三方內容著作權仍屬 Lukasz Jagiello（2026），同樣為 MIT 授權，詳見
[`NOTICE`](NOTICE)。
