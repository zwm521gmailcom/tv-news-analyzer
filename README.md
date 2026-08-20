<!-- Language Switcher -->
<p align="right"><a href="README.md">🇬🇧 English</a> · <a href="README.zh.md">🇨🇳 中文</a></p>

# TradingView News Monitor

> Real-time TradingView bilingual news scraper with SQLite storage, rich terminal UI, web dashboard, analytics page, relationship graphs, 3D graph, and a **dual-system AI insight engine** (period insights + global narrative).

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Status](https://img.shields.io/badge/status-active-brightgreen)
![DB](https://img.shields.io/badge/SQLite-local-003B57)
![Data](https://img.shields.io/badge/data-local--only-blue)
![AI](https://img.shields.io/badge/AI-MiniMax--M3-cc785c)
![Version](https://img.shields.io/badge/version-v1.1.1-blue)

---

## 📸 Screenshots

### 🏠 Dashboard (Home)

![Dashboard](docs/screenshots/01-dashboard.png)

### 📊 Analytics (McKinsey-style)

![Analytics](docs/screenshots/02-analytics.png)

### 🕒 AI Market Insights (Timeline + 4-period tabs + global narrative)

![Timeline](docs/screenshots/03-timeline.png)

### 🕸️ Relationship Graph

![Graph](docs/screenshots/05-graph.png)

### 🌀 3D Graph (1404 nodes / 723 edges)

![3D Graph](docs/screenshots/06-graph3d.png)

### 🛠️ System Overview (with AI management + multi-period insight status)

![System](docs/screenshots/07-system.png)

### 💾 Data Backup & Restore (manual management)

![Backup](docs/screenshots/08-backup.png)

### 📜 AI Insight History (4-period filter + continuity comparison)

![History](docs/screenshots/09-history.png)

### ⚙️ Backfill Parameters + AI Insight Config

![Config](docs/screenshots/10-config.png)

---

## ✨ Features

### Data Collection

| Module | Description |
|------|------|
| 🌍 **Bilingual concurrent scraping** | Scrapes both English (`en`) and Chinese (`zh-Hans`), up to 600 items per round, supports anonymous mode |
| 🔄 **Incremental polling** | Records last timestamp, returns only new entries, nonce parameter bypasses CDN cache |
| 📰 **Full body scraping** | Detail API for full text (AST → plain text), background async, non-blocking display |
| 🧠 **Auto market inference** | Three-level inference (exchange prefix → provider name → title keywords), covers crypto/stock/forex/futures/index/economic |
| 💾 **Local-first** | SQLite storage, no cloud dependency; all data lives on your machine |
| 🔐 **Optional authentication** | Cookie mode enabled when `data/cookies.txt` has content; auto-degrades to anonymous when empty |

### Web Dashboard (9 pages, unified dark Kraken style)

| Page | Function |
|------|------|
| 🏠 `/` | News board (real-time filter + full-text modal) |
| 📊 `/analytics` | McKinsey-style data analysis (time/source/market distribution) |
| 🕒 `/timeline` | **AI Insights** (4-period tabs + global narrative + cross-event network) |
| 🕸️ `/graph` | Relationship graph (events/markets/symbols) |
| 🌀 `/graph3d` | 3D graph (1404 nodes / 723 edges) |
| 🛠️ `/system` | System overview + **AI config + multi-period insight status** |
| 💾 `/backup` | Data backup & restore (manual, **never auto-deleted**) |
| ⚙️ `/config/backfill` | Backfill parameters + **AI insight config (read-only)** |
| 📜 `/history` | **AI insight history timeline** (4-period filter + continuity comparison) |

### 🧠 AI Insights Dual System (v1.1.0+)

The project maintains **two completely isolated** AI systems to avoid mutual interference:

| System | Data Scope | Refresh Frequency | Output |
|---|---|---|---|
| **AI Period Insights** | 1d / 3d / 7d / 30d windows | Daily at 04:00 (4 periods in one run) | summary + 5-10 themes + 3-6 bull/bear sectors (with status: new/continued/resolved) |
| **AI Global Narrative** | Past 24h cross-region associations | Every 6 hours | 5 viewpoints + 5 insights (24h summary + 6h detail) |

**Hard rules for both systems**:
- ⏰ **Timestamp injection**: Every news fed to AI has a `[MM-DD HH:MM · Xh ago]` marker; AI anchors numerical quotes to specific news time
- 📚 **History context**: Generation pulls prior N same-period history (period: daily=3, 3day/weekly/monthly=2; global: 3), AI explicitly labels "continued/reversed/resolved"
- 🛡️ **Complete isolation**: Period insights and global narrative have **independent prompts + independent history tables + independent APIs**, no interference
- 💾 **History preserved**: All generations append to history table, permanently retained, traceable on `/history` page

**Sample output (v3 actual generation)**:
> 📌 US Treasury intervenes in bond market, USD hits 3-month low, gold retreats to 4500
> summary: Continues the previous "US bond buyback eases panic" narrative, but reverses in latest 6h: [08-20 12:14] USD falls to 3-month low... [08-20 12:05] gold gives back multi-week highs... Reuters comments 'Bonds bounce on US buybacks, but relief may be brief' suggests intervention effect uncertain

### 🛡️ Data Protection

- `db/database.py:init_db()` strictly idempotent (`CREATE TABLE IF NOT EXISTS` + column existence checks)
- Grep `DELETE FROM raw_news` across all code = **0 hits**
- Backup strategy: all backups **never auto-deleted** (retention policy disabled), managed manually on `/backup` page
- `MINIMAX_API_KEY` in `.env` **never uploaded** (API responses only return masked `sk-c…uqkM`)

---

## 🚀 Quick Start

### One-Command Init (Recommended)

```bash
git clone https://github.com/zwm521gmailcom/tv-news-analyzer.git
cd tv-news-analyzer

# Idempotent init: create directories + tables + migrations + placeholder files
bash scripts/init.sh

# Install dependencies
pip install -r requirements.txt

# Start News + Web
bash tvnews.sh start

# Open browser
open http://localhost:5888/
```

> `scripts/init.sh` is **idempotent** — re-running won't delete any data. Existing DB/tables/rows are all preserved. See `bash scripts/init.sh --help` for details.

### Manual Steps

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy config
cp .env.example .env
# Edit .env (at minimum set TV_FETCH_LANGS and HTTP_PROXY)

# 3. Start
chmod +x tvnews.sh
./tvnews.sh start

# Status / stop / restart
./tvnews.sh status
./tvnews.sh stop
./tvnews.sh restart
```

After starting, open in browser:

| Route | Page |
|------|------|
| http://localhost:5888/ | News board (dark style + full-text modal) |
| http://localhost:5888/analytics | Analytics page (McKinsey-style) |
| http://localhost:5888/timeline | **AI Insights** (4-period tabs + global narrative + cross-event network) |
| http://localhost:5888/graph | Relationship graph |
| http://localhost:5888/graph3d | 3D graph |
| http://localhost:5888/system | System overview + AI config + multi-period status |
| http://localhost:5888/backup | Data backup & restore (manual) |
| http://localhost:5888/config/backfill | Backfill parameters + AI insight config |
| http://localhost:5888/history | **AI insight history timeline** |

### Historical Data Backfill (After First Run)

```bash
# Body backfill (after first start, fetch full text for historical data)
python3 scripts/backfill_story_body.py --limit 2700 --delay 0.3

# Field backfill (infer market / sector / country from raw_json)
python3 scripts/backfill_raw_fields.py --dry-run   # preview
python3 scripts/backfill_raw_fields.py --overwrite # write
```

### Terminal Query

```bash
# Recent 24h news
python3 run.py --query

# Filter by language + market
python3 run.py --query --lang zh-Hans --market crypto --limit 30

# Search by symbol
python3 run.py --query --symbol BTCUSDT --limit 10

# Single fetch (for testing)
python3 run.py --once
```

---

## 📁 Directory Structure

```
tv-news-analyzer/
├── run.py                      # Terminal entry (polling + query)
├── tvnews.sh                   # One-command script (start/stop/status/restart)
├── scripts/
│   └── init.sh                 # Idempotent init (dirs + tables + migrations)
├── DESIGN.md                   # Design system spec
├── .env.example                # Config template (no secrets)
├── requirements.txt
│
├── config/settings.py          # All constants (loaded from .env)
├── core/                       # fetcher / cookie_manager / rate_limiter / ws_fetcher / minimax_client
├── db/                         # models / database (init_db idempotent) / repository
├── pipeline/                   # orchestrator / scheduler / global_narrative / period_insights
├── display/console.py          # rich terminal output
├── web/                        # Flask API + 9 pages (index/analytics/timeline/graph/graph3d/system/backup/config_backfill/history)
│
└── scripts/
    ├── init.sh                 # Idempotent init
    ├── backfill_story_body.py  # Body backfill
    ├── backfill_raw_fields.py  # Field backfill
    ├── sync_to_obsidian.py     # Sync to Obsidian
    └── sync_raw_to_obsidian.py
```

---

## 🛡️ Data Protection

**Important: Your data will not be damaged by this project, nor will it be pushed to GitHub.**

| Path | Tracked? | Description |
|------|----------|------|
| `data/tv_news.db` | ❌ | SQLite database (all scraped news) |
| `data/cookies.txt` | ❌ | TradingView login credentials |
| `data/cookies.json` | ❌ | Cookie cache (auto-generated) |
| `backups/*.db.gz` | ❌ | Manual backup archives |
| `logs/*.log` | ❌ | Runtime logs |
| `.env` | ❌ | Local config (with proxy, API key) |
| `.env.example` | ✅ | Template (no secrets) |
| `data/.gitkeep` etc. | ✅ | Placeholder files (so empty dirs can be git-tracked) |

See [`.gitignore`](.gitignore) for full rules.

**The program does not delete your data**:
- `db/database.py:init_db()` strictly idempotent (`CREATE TABLE IF NOT EXISTS` + column existence checks)
- Grep `DELETE FROM raw_news` across all code = **0 hits**
- Backup strategy: all backups **never auto-deleted** (retention policy disabled), managed manually on `/backup` page

---

## 🔐 Privacy & Security

**Your credentials will not be pushed to GitHub by this project.**

`.gitignore` strictly excludes these sensitive files:

| File | Risk | Excluded |
|------|------|----------|
| `.env` | Your `MINIMAX_API_KEY` + TradingView cookies + proxy | ✅ |
| `data/cookies.txt` | TradingView login credentials (sessionid / device_t / sp etc.) | ✅ |
| `data/cookies.json` | Cookie cache (auto-generated) | ✅ |
| `data/*.db` | SQLite database (all scraped news) | ✅ |
| `backups/*.db.gz` | Manual backup archives | ✅ |
| `logs/*.log` | Runtime logs (may contain URLs / cookies) | ✅ |

**Code audit results** (latest commit):
- ✅ Real `MINIMAX_API_KEY` in all git history = **0 hits**
- ✅ Real TradingView sessionid in all git history = **0 hits**
- ✅ Cookie fields in `tests/` are all fake fixtures (`abc123` / `xyz789`)
- ✅ Release assets contain only PNG screenshots (no .env / .db / .log)
- ✅ API key in Web UI is shown only in masked form (`sk-c…uqkM` 125 chars)

**`.env.example` is a clean placeholder template**; all real values are read from your local `.env` and **never** appear in the repository.

**If you suspect key leak**:
1. Immediately rotate API key at [MiniMax Console](https://api.minimaxi.com)
2. Re-login to TradingView to refresh cookies
3. `git log --all -p | grep "sk-cp-"` to verify no leak in history (should be 0 matches)

---

## ⚙️ Configuration (.env)

### Core Toggles

| Variable | Default | Description |
|------|--------|------|
| `FETCH_STORY_BODY` | `false` | When `true`, each new article triggers detail API call for full body |

### News Sources

| Variable | Default | Description |
|------|--------|------|
| `TV_FETCH_LANGS` | `en,zh-Hans` | Comma-separated languages to scrape concurrently |
| `TV_FILTER_LANG` | `en` | Backward-compatible single-language mode |
| `TV_FILTER_SYMBOLS` | empty | Filter by symbol, e.g. `BINANCE:BTCUSDT` |
| `TV_FILTER_MARKETS` | `bond,corp_bond,crypto,economic,etf,forex,futures,index` | Market whitelist |
| `TV_FILTER_CORP_ACTIVITIES` | empty | Corp activities: `earnings` `ipo` `dividends` etc. |
| `TV_FILTER_ECONOMIC_CATEGORIES` | empty | Macro: `gdp` `labor` `trade` `money` etc. |
| `TV_FILTER_PROVIDERS` | empty | Provider whitelist |

### Polling & Storage

| Variable | Default | Description |
|------|--------|------|
| `data/cookies.txt` | empty | The only manual cookie input file |
| `HTTP_PROXY` | empty | Proxy, e.g. `http://127.0.0.1:7890` |
| `ENABLE_PRICE_TRACKER` | `false` | WebSocket real-time prices (requires valid Cookie) |
| `TV_PRICE_SYMBOLS` | `BTC/ETH/SOL/BNB/XRP` | Real-time price symbol list |

### AI Insights (v1.1.0+)

| Variable | Default | Description |
|------|--------|------|
| `MINIMAX_API_KEY` | empty | MiniMax API key (v1.1+ only AI provider) |
| `MINIMAX_BASE_URL` | `https://api.minimaxi.com/anthropic/v1` | MiniMax Anthropic-compatible endpoint |
| `MINIMAX_MODEL` | `MiniMax-M3` | Default model |

> After configuring API key in `.env`, you **must restart the News + Web service** for it to take effect. The `/system` and `/config/backfill` pages will display the active configuration (key shown as masked `sk-c…uqkM`).

---

## 🏗️ System Architecture

### Data Collection Flow

```
python3 run.py
│
├─ init_db()                  Restore last timestamp from DB (no re-scraping on restart)
└─ asyncio.gather()
    │
    ├─ _poll_loop (every 60s)
    │   ├─ fetch_all_langs()          lang:en + lang:zh-Hans concurrent requests
    │   ├─ Incremental filter: only return published > last timestamp
    │   ├─ Dedup (INSERT OR IGNORE)
    │   ├─ show_raw() immediately
    │   └─ create_task(fetch body)   Background async, 0.5s interval per item
    │
    └─ _price_loop (optional, WebSocket)
        └─ Subscribe real-time prices
```

### Web Server

```
Flask (port 5888)
├── /api/* (JSON)
│   ├── /api/stats                  Overall stats
│   ├── /api/news                   Paginated news
│   ├── /api/news_detail            Single detail (with story_body)
│   ├── /api/analytics              Analytics data
│   ├── /api/runtime                Runtime state (anonymous / Cookie)
│   ├── /api/backup/*               Backup & restore
│   ├── /api/system                 System overview
│   ├── /api/system/ai_status       AI config + multi-period insight status (v1.1)
│   ├── /api/insights/period        Read 4-period insights (v1.1)
│   ├── /api/insights/generate      Force regenerate (v1.1)
│   ├── /api/insights/history       Period insight history (v1.1)
│   ├── /api/insights/compare       Period insight comparison (v1.1)
│   ├── /api/global_narrative       Global narrative (v1.1: 6h/24h dual-window + history context)
│   ├── /api/global_narrative/history  Global narrative history (v1.1)
│   └── /api/config/*               Config
└── /* (HTML)
    ├── /                           Dashboard
    ├── /analytics                  Analytics
    ├── /timeline                   AI Insights (4 periods + global narrative)
    ├── /graph                      Relationship graph
    ├── /graph3d                    3D
    ├── /system                     System overview + AI config
    ├── /backup                     Backup
    ├── /config/backfill            Backfill + AI config
    └── /history                    AI insight history timeline
```

---

## 🗄️ Database Schema

`raw_news` is a hybrid table of "TradingView raw fields + locally derived fields". It only stores what the API returns and its derived results, not request-layer filter dimensions like `priority` / `format`.

| Type | Field | Description |
|------|------|------|
| Raw API field | `id` | TradingView news ID |
| Raw API field | `title` | Title |
| Raw API field | `short_desc` | `short_description` |
| Raw API field | `urgency` | Urgency |
| Raw API field | `provider` | Source organization |
| Raw API field | `published` | Publish timestamp (Unix) |
| Raw API field | `symbols` | Trade pairs extracted from `relatedSymbols` |
| Raw API field | `is_flash` | Flash news flag |
| Raw API field | `raw_json` | Original API payload |
| Locally derived | `story_body` | Plain text from detail API |
| Locally derived | `lang` | Language of this request |
| Locally derived | `market` | Market type inferred from symbols/provider/title |
| Locally derived | `sector` | Sector extracted from `logoid` |
| Locally derived | `country` | Country/region extracted from `logoid` |
| Locally derived | `fetched_at` | Local fetch time |

---

## 🤔 FAQ

**Q: Will it re-scrape historical data after restart?**
No. The scheduler restores the latest timestamp from the DB `system_state` table and only fetches new entries.

**Q: `story_body` is all empty?**
The list API doesn't return body content. Enable `FETCH_STORY_BODY=true` for new articles; use backfill scripts for historical data.

**Q: Can it work with empty `data/cookies.txt`?**
Yes. Empty `cookies.txt` triggers anonymous mode; titles and short summaries are still fetched. Once populated, `cookies.json` is auto-generated and Cookie mode is enabled.

**Q: Port 5888 in use on startup?**
`server.py` auto-detects and terminates the process holding port 5888; no manual action needed.

**Q: Will there be duplicate news between English and Chinese?**
Chinese/English versions from the same publisher are separate entries with different IDs, both stored with their respective `lang` field.

**Q: How to view only crypto news?**
Click the ₿ Crypto filter on the web dashboard; use `python3 run.py --query --market crypto` on terminal.

**Q: DB is full or want to clean history?**
This project **never auto-deletes any data**. For manual management, visit http://localhost:5888/backup.

**Q: What's the use of AI timestamp? Why did AI use old gold price before?**
Every news fed to AI has a `[08-20 12:14 · 2h ago]` marker; AI anchors numerical quotes to this time. If the same day has both "gold $2400" and "gold $4500" news, the prompt hard rule requires AI to use **the latest one**; old numbers are only for historical comparison. If you see AI using old numbers, it might be cache (page auto-refreshes every 60s); you can also click the "🔄 Refresh" button on `/timeline` to force regenerate.

**Q: What's the difference between global narrative and period insights?**
- **Period insights** (4 tabs in /timeline + /history): Look at N-day trends, each period independent. Daily looks at past 24h, weekly at past 7 days. Runs once daily at 04:00.
- **Global narrative** (top "AI Global Narrative" section in /timeline): Looks at past 24h cross-region associations, runs every 6h. Emphasizes "what just happened" + "historical narrative continuity".
- They are **completely independent**, sharing no prompts or history tables.

---

## 📦 Release Notes

### v1.1.1 (2026-08-20) — Maintenance Update

- 📜 **/history dual-date display** (commit `58efe4b`): each insight now shows both reasoning time + news range; insights sorted by `period_end DESC` (news date as timeline, not AI write time)
- 🔐 **Privacy & Security section** (commit `6aad615`): README documents all .gitignore exclusions + code audit results
- 🗑️ **Remove /map page** (commit `5a8ec43`): clean up by user request, geographic info now in /analytics

### v1.1.0 (2026-08-20) — AI Dual System + History Tracing

**New**:
- 🧠 **AI Period Insights**: 4 periods (daily / 3day / weekly / monthly), auto-generated at 04:00 daily
- 🧠 **AI Global Narrative**: every 6h, injects 6h detail + 24h summary dual-window + 3 history contexts
- ⏰ **Timestamp hard rule**: every news fed to AI has `[MM-DD HH:MM · Xh ago]` marker, AI quotes numbers anchored to specific time
- 📚 **History traceable**: `period_insights_history` table append-only retains all generations; `global_narratives` table is the history itself
- 📜 **`/history` page**: 4-period filter + continuity comparison card + timeline (period color-coded)
- 🛠️ **`/system` AI management area**: provider/model/base_url/api_key (masked) + 4-period insight status
- ⚙️ **`/config/backfill` AI config area**: read-only config + `.env` warning + multi-period insight jump link
- 🔌 **8 new APIs**: `/api/insights/{period,generate,history,compare}` + `/api/system/ai_status` + `/api/global_narrative/history`

**Improvements**:
- 🎨 9 pages unified layout: sticky topbar + body `min-height: 100vh` natural scroll
- 🔤 Font unified: H1 24px / H2 15px / H3 14px / Body 14px / Caption 12px / Meta 11px
- 🧹 Delete `pipeline/ai_narrator.py` (Ollama 100% removed)
- 🔧 MiniMax M2.7 → M3
- 🗄️ Add `references_history_ids` column to global_narratives table

**Fixes**:
- Prevent AI using stale prices (timestamp anchor + hard rule: "use latest")
- Prevent 4h vacuum period (6h scheduler + 60s page auto-refresh)

### v1.0.0 (2026-08-18) — First Public Release

- Bilingual concurrent scraping (en + zh-Hans)
- Web dashboard (Kraken dark style)
- Analytics page (McKinsey style)
- Relationship graph + 3D graph
- System overview + Data backup & restore
- 8 page screenshots

---

## 📜 License

Not specified (LICENSE file not yet added). For commercial or redistribution use, please contact the author.
