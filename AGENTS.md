# AGENTS.md

> TradingView 双语新闻抓取 + AI 双体系洞察平台（v1.1.1）。本文件供 AI Agent（OpenCode/Codex/Cursor/Aider/Devin/Gemini CLI 等）读懂项目架构 + 设计原则 + 关键约束。

## 1. 项目一句话

实时抓取 TradingView 双语新闻，落 SQLite 库，提供 9 页 Web 看板（暗色 Kraken 风格）+ 终端 rich 输出 + **AI 双体系洞察**（周期洞察 + 全局叙事）。

## 2. Setup commands

```bash
# 一键初始化（幂等：建目录 + 建表 + 迁移 + 占位文件）
bash scripts/init.sh

# 安装依赖
pip install -r requirements.txt

# 配置 .env（至少设置 TV_FETCH_LANGS + HTTP_PROXY + MINIMAX_API_KEY）
cp .env.example .env
# 编辑 .env

# 启动 News + Web
bash tvnews.sh start   # 启动
./tvnews.sh status     # 状态
./tvnews.sh stop       # 停止
./tvnews.sh restart    # 重启
```

Web 默认端口 **5888**。启动后访问 `http://localhost:5888/`。

## 3. 关键架构原则（**必读**）

### 3.1 AI 双体系完全隔离

项目维护**两套完全独立的 AI 体系**（v1.0 → v1.1 设计核心）：

| 体系 | 数据范围 | 刷新频率 | Prompt 入口 | 历史表 | API 入口 |
|---|---|---|---|---|---|
| **AI 周期洞察** | 1d / 3d / 7d / 30d | 每天 04:00 一次 | `pipeline/period_insights.py` | `period_insights_history` | `/api/insights/*` |
| **AI 全局叙事** | 过去 24h 跨区域 | 每 6h 一次 | `pipeline/global_narrative.py` | `global_narratives`（本身即历史） | `/api/global_narrative*` |

**隔离原则（不要破坏）**：
- ❌ 不要让两个体系**共享 prompt 模板**或**共享历史 context**
- ❌ 不要把 `global_narratives` 表当作 `period_insights` 的二级缓存
- ✅ 两个体系的**输出字段、状态机、API 路径**都独立

### 3.2 时间戳硬规则（v3 引入）

**每条新闻进 AI 之前必须带时间戳**：

```
- [08-20 12:14 · 2小时前] [Reuters/crypto] Spot gold retreats from 2-month peak
  摘要: ...
```

格式：`- [{abs_ts} · {rel}] [{provider}/{market}] {title}` + 摘要

**Prompt 硬规则**（已在两个体系都注入）：
1. 引用具体数字时锚定到**该数字出现的新闻时间**
2. 同一标的数字差异大时（黄金 2400 vs 4500），以**最新一条为准**
3. 预测数字必须基于最新 + 当前趋势，不引用旧价位

**绝对不要**让 AI 直接用 raw 数字 — 必须经过时间戳包装。

### 3.3 历史 context 注入（v3 引入）

两个体系生成时**都拉历史 context**（但方式不同）：

| 体系 | history 拉取规则 | 注入方式 |
|---|---|---|
| 周期洞察 | **纯同周期**：daily=3 prior, 3day/weekly/monthly=2 prior | prompt 完整 prior 列表 |
| 全局叙事 | 前 3 个 global_narrative（无 period 区分） | prompt 摘要列表 + key symbols |

**纯同周期 vs 多尺度**：周期洞察**不混合**子周期（不要 3day 里塞 3 个 daily，会淹没 AI 上下文）。

**排序硬规则**：历史洞察列表按 `period_end DESC`（**新闻日期**）排序，不是按 `generated_at DESC`（AI 写的时间）。洞察是"过去 N 天新闻"的总结，**应该按新闻时间线排序**。

### 3.4 绝不删数据（项目最硬约束）

```bash
# 验证（应该 0 命中）：
grep -rn "DELETE FROM raw_news" .
grep -rn "DROP TABLE" .
```

- `db/database.py:init_db()` **严格幂等**：`CREATE TABLE IF NOT EXISTS` + 列存在性检查
- 所有备份**永不自动删除**（保留策略已禁用）
- 任何新代码不允许**新增**删除路径

### 3.5 本地优先 / 隐私

- 所有数据本地 SQLite（`data/tv_news.db`，**不进 git**）
- `.env` 含 API key + cookies，**绝不上传**
- Web UI 永远只显示 **mask 后的 API key**（`sk-c…uqkM` 125 字符）

`.gitignore` 排除：`data/` `backups/` `logs/` `.env` `data/cookies.*` `playwright-cli/` 等。

## 4. Project layout

```
tv-news-analyzer/
├── run.py                      # 终端入口（轮询 + 查询）
├── tvnews.sh                   # 一键启动脚本（start/stop/status/restart）
├── AGENTS.md                   # ← 本文件，AI Agent 速查
├── README.md                   # 英文（GitHub 默认）
├── README.zh.md                # 中文
├── .env.example                # 配置模板（无敏感信息）
├── requirements.txt            # Python 依赖
│
├── config/settings.py          # 全部常量（从 .env 加载）
├── core/                       # 基础组件：fetcher / cookie_manager / rate_limiter / ws_fetcher / minimax_client
├── db/                         # 数据库：models / database（init_db 幂等迁移） / repository
├── pipeline/                   # 核心 pipeline：orchestrator / scheduler / global_narrative / period_insights
├── display/console.py          # rich 终端输出
├── web/                        # Flask API + 9 个页面（index/analytics/timeline/graph/graph3d/system/backup/config_backfill/history）
├── scripts/                    # 启动脚本 + 回填脚本
├── tests/                      # 单元测试
├── docs/                       # 长文档 + screenshots
└── backups/, data/, logs/      # 运行时数据（不进 git）
```

## 5. 关键文件速查

| 任务 | 文件 | 备注 |
|---|---|---|
| 添加新 web 页面 | `web/{name}.html` + `web/{name}.js` + `web/server.py` 加 `@app.route("/{name}")` | nav 链接通过 `web/shared-ui.js` 的 `NAV_ITEMS` 数组统一管理 |
| 加新 API | `web/server.py` | 不要忘了 PRG 返回格式 `jsonify({ok: True, ...})` |
| 加新 period | `pipeline/period_insights.py` 的 `PERIODS` + `PERIOD_CONFIG` + `HISTORY_CONTEXT_RULES` | **3 个 dict 必须同步** |
| 改 AI prompt | `pipeline/period_insights.py:_build_period_prompt()` 或 `pipeline/global_narrative.py:_build_global_view_prompt()` | 必须包含【时效校验硬规则】+【中文引用用「」】 |
| 改 web 布局 | 9 个 HTML 文件共享的 `body { min-height: 100vh }` + `topbar { position: sticky; top: 0 }` 模式 | 见 `web/system.html` 作参考 |
| 加新 i18n 键 | `web/i18n.js` 同时改 zh + en | `nav.*` 用于顶部 nav，`field.*` 用于配置字段 |
| 改 scheduler | `pipeline/scheduler.py` | 当前：03:00 备份 + 04:00 4 period insights + 6h global narrative |
| 加新 history 表 | `db/database.py` 加 DDL（`CREATE TABLE IF NOT EXISTS`） | `init_db()` 自动迁移 |

## 6. 常见任务速查

### 6.1 触发一次 4-period 强制重生成

```bash
# 单个 period
curl -X POST 'http://localhost:5888/api/insights/generate?period=daily'

# 全局叙事
curl -X POST 'http://localhost:5888/api/generate_global?hours=24'
```

### 6.2 查看 AI 配置 + 多周期状态

```bash
curl -s http://localhost:5888/api/system/ai_status | python3 -m json.tool
```

### 6.3 看 history 时间线（含推理日期 + 新闻范围）

```bash
curl -s 'http://localhost:5888/api/insights/history?period=daily&limit=10' | python3 -m json.tool
```

### 6.4 数据库直接查询（不通过 API）

```bash
sqlite3 data/tv_news.db "
  SELECT id, period, datetime(period_start,'unixepoch','+8 hours') AS ps_bjt,
         datetime(period_end,'unixepoch','+8 hours') AS pe_bjt,
         datetime(generated_at,'unixepoch','+8 hours') AS ga_bjt,
         news_count
  FROM period_insights_history
  ORDER BY period_end DESC LIMIT 10;
"
```

## 7. 绝对不要做（红线）

| 红线 | 原因 |
|---|---|
| ❌ 添加任何 `DELETE FROM raw_news` / `DELETE FROM backups` 路径 | 项目原则"永不删数据" |
| ❌ 把真实 API key 写进代码 / 测试 / 文档 | 隐私泄露（`/api/system/ai_status` 只回 mask） |
| ❌ 在 prompt 里用英文双引号包裹中文引用 | 破坏 JSON 解析（应该用「」或『』） |
| ❌ 让两个 AI 体系共享 prompt 模板 | 破坏隔离原则 |
| ❌ 把 `generated_at` 当作"洞察覆盖的新闻时间" | 应该是 `period_end`（新闻截止时间） |
| ❌ 在 web 端明文返回完整 API key | 必须 mask（`sk-c…uqkM` 125 字符） |
| ❌ 修改 init_db() 删除列或表 | init_db 是幂等迁移，不能破坏历史数据 |
| ❌ 在 commit 里包含 `.env` / `data/*.db` / `data/cookies.*` | `.gitignore` 已排除，要 verify |

## 8. 双语 README 约定

- `README.md` = 英文（GitHub 默认显示）
- `README.zh.md` = 中文（Jackey 工作语言）
- 两个文件**顶部都有语言切换链接**：

```html
<p align="right">🇬🇧 English · 🇨🇳 中文</p>
```

修改时**两个文件同步更新**（不要只改一个）。

## 9. 命名约定

- 文件：`snake_case.py`（如 `period_insights.py`）
- 类：`PascalCase`（如 `PeriodInsights`）
- 函数/变量：`snake_case`
- 常量：`UPPER_SNAKE_CASE`
- HTML 元素 ID：`kebab-case`（如 `filter-bar`）
- CSS 类：`kebab-case`（如 `.timeline-card`）
- 命名空间分隔：用 `.`（如 `nav.home`、`field.provider`）

## 10. 调试技巧

```bash
# 后台服务实时日志
tail -f logs/web.log

# 端口 5888 占用排查
lsof -i:5888

# DB 锁检查
sqlite3 data/tv_news.db ".timeout 5000" "BEGIN IMMEDIATE; ROLLBACK;"

# 重置某表（注意：会丢数据！）
sqlite3 data/tv_news.db "DELETE FROM period_insights_history WHERE period='daily';"
```

## 11. CI / 发布

- 主分支：`main`
- 公开 repo：`https://github.com/zwm521gmailcom/tv-news-analyzer`
- 每次重要 commit 配 **GitHub Release**（v1.0.0 / v1.1.0 / v1.1.1）
- Release assets 必须含：
  - 9-10 张截图（`docs/screenshots/*.png`，全页面截图）
  - `git archive` 打的 source code zip（4 MB 左右）
- commit message 用 conventional commits：`feat:` / `fix:` / `docs:` / `chore:` / `refactor:`
