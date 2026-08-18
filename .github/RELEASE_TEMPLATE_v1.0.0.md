# v1.0.0 — Initial Public Release (2026-08-18)

第一个公开版本。TradingView 双语新闻实时抓取 + 本地 SQLite 存储 + Flask Web 看板（7 个页面）。

## ✨ 核心功能

- 🌍 **双语并发抓取**：英文 + 中文，每轮最多 600 条
- 🔄 **增量轮询**：重启不重抓历史（基于 `system_state` 表的最新时间戳）
- 📰 **正文抓取**：详情接口 → AST → 纯文本，后台异步
- 🧠 **市场自动推断**：三级推断覆盖 crypto / stock / forex / futures / index / economic
- 🖥️ **Web 看板（7 页）**：index / analytics / timeline / map / graph / graph3d / system + 手动 backup
- 💾 **本地优先**：SQLite 单文件存储，无云端依赖
- 🔐 **登录态可选**：`data/cookies.txt` 空时自动匿名模式

## 🛡️ 数据安全

- ✅ `db/database.py:init_db()` 严格幂等（`CREATE TABLE IF NOT EXISTS` + 列存在性检查）
- ✅ 全代码 grep `DELETE FROM raw_news` = **0 命中**
- ✅ 备份永不自动删除（保留策略已禁用），由你在 `/backup` 页面手动管理
- ✅ `.gitignore` 排除 data/、backups/、cookies、.env、logs

## 🚀 快速开始

```bash
git clone https://github.com/zwm521gmailcom/tv-news-analyzer.git
cd tv-news-analyzer
bash scripts/init.sh          # 幂等初始化（不删任何数据）
pip install -r requirements.txt
cp .env.example .env          # 编辑 .env
bash tvnews.sh start
open http://localhost:5888/
```

## 📦 系统要求

- Python 3.10+
- macOS / Linux（已测试 macOS 14+，APFS）
- 系统 `curl`（TradingView 新闻列表抓取用）

## 📁 目录结构

```
.
├── run.py                      # 终端入口
├── tvnews.sh                   # 一键启停
├── scripts/
│   ├── init.sh                 # 幂等初始化
│   ├── backfill_story_body.py  # 正文回填
│   ├── backfill_raw_fields.py  # 字段回填
│   └── sync_*_to_obsidian.py   # Obsidian 同步
├── config/settings.py
├── core/                       # fetcher / cookie / rate / ws
├── db/                         # models / database / repository
├── pipeline/                   # orchestrator / scheduler
├── display/console.py
├── web/                        # Flask + 7 页
├── tests/
└── docs/                       # 设计文档
```

## 🔗 链接

- **Repository**: https://github.com/zwm521gmailcom/tv-news-analyzer
- **Issues**: https://github.com/zwm521gmailcom/tv-news-analyzer/issues

## 📝 已知限制

- WebSocket 实时价格需要有效 Cookie（`data/cookies.txt`）
- 约 15% 文章正文为空（快讯 / SEC 原始申报 / 付费内容等，接口本身不返回）
- 首次启动后建议跑 `python3 scripts/backfill_story_body.py --limit 2700 --delay 0.3` 补齐历史正文

## 📜 License

未指定（暂未添加 LICENSE 文件）。如需商用或二次发布请联系作者。
