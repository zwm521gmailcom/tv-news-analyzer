# 更新日志

## 2026-04-25 — 全站导航统一与匿名运行态

### 背景

Web 看板、分析页、时间线、地图、关系图与 3D 图谱原本各自维护导航和运行态展示，容易出现页面不一致；同时 Cookie 行为已经切换为 `data/cookies.txt` 唯一人工入口，需要在文档中明确匿名模式与 Cookie 模式的边界。

### 更新内容

| 文件 | 修改 |
|------|------|
| `web/shared-ui.css` | 统一全站导航栏样式、运行态徽章样式与旧导航隐藏规则 |
| `web/shared-ui.js` | 统一注入导航栏与运行态徽章 |
| `web/server.py` | 增加 `/api/runtime`，并将静态资源路径固定到 `/static` |
| `web/index.html` | 首页显示匿名 / Cookie 状态徽章 |
| `web/analytics.html` | 接入统一导航与运行态徽章 |
| `web/timeline.html` | 接入统一导航与运行态徽章 |
| `web/map.html` | 接入统一导航与运行态徽章 |
| `web/graph.html` | 接入统一导航与运行态徽章 |
| `web/graph3d.html` | 接入统一导航与运行态徽章 |
| `README.md` | 补充共享导航、页面路由、`/api/runtime` 与 `data/cookies.txt` 行为说明 |

### 结果

- 所有 Web 页面共享同一导航结构
- 首页和其它页面统一显示匿名 / Cookie 模式
- `data/cookies.txt` 为空时自动匿名运行，填写后同步生成 `data/cookies.json`

## 2026-04-24 — 删除 entity 匹配链

### 背景

`FinanceDatabase` 只存在于 `core/symbol_matcher.py` 的兜底逻辑里，但主流程没有消费 entity 匹配结果。为减少无用依赖和启动时报错，移除运行时 entity 匹配链与相关辅助脚本。

### 删除/简化

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/symbol_matcher.py` | 删除 | 新闻标的 → Obsidian entity 匹配器 |
| `pipeline/orchestrator.py` | 修改 | 移除 SymbolMatcher 初始化 |
| `pipeline/scheduler.py` | 修改 | 不再传入 entity 相关配置 |
| `config/settings.py` | 修改 | 删除 `VAULT_PATH`、`CREATE_ENTITY_STUBS` |
| `scripts/generate_entity_files.py` | 删除 | entity 生成辅助脚本 |
| `scripts/fix_entity_raw_links.py` | 删除 | entity 链接修复辅助脚本 |

### 保留

- TradingView 新闻抓取与增量轮询
- SQLite 持久化存储
- 正文抓取与回填
- Web 看板 / 数据分析页
- Obsidian raw/news/symbol 同步

## 2026-04-17 — Entity 匹配前移至 Pipeline 阶段

### 背景

Entity 匹配逻辑从 `sync_raw_to_obsidian.py`（同步阶段）前移到 Pipeline（抓取/存储阶段）。新闻入库时即完成 entity 匹配，结果存入 `raw_news.entities`。同步脚本退化为纯读 DB → 写 Obsidian 文件的工具。

---

### 架构变更

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/symbol_matcher.py` | 新建 | SymbolMatcher 类 + 数据加载函数（从 sync 脚本移出） |
| `pipeline/orchestrator.py` | 修改 | 集成 SymbolMatcher，新增 `_match_and_save_entities` 方法 |
| `pipeline/scheduler.py` | 修改 | Orchestrator 初始化时传入 `vault_path` 和 `create_stubs` |
| `config/settings.py` | 修改 | 新增 `VAULT_PATH`、`CREATE_ENTITY_STUBS` 配置项 |
| `scripts/sync_raw_to_obsidian.py` | 大幅简化 | 移除 SymbolMatcher 类、股票数据加载函数、entity 匹配逻辑；改为纯读 `raw_news.entities` |

### Phase 1 Bug 修复

| 问题 | 修复 |
|------|------|
| 多个 symbol 匹配同一 entity（如 BITSTAMP:BTCUSD + BINANCE:BTCUSDT → BTC 出现两次） | `entity_paths` 收集后和 `yaml_list()` 输出前双重去重：`list(dict.fromkeys(entity_paths))` |

### 保留的功能

- TradingView 新闻抓取（双语 en/zh-Hans 并发）
- 增量轮询（基于 `system_state` 时间戳）
- 新闻正文抓取（后台异步）
- SQLite 持久化存储
- 终端彩色展示（`show_raw`）
- Web 看板（`/`）
- 数据分析页（`/analytics`）
- Obsidian 同步（`sync_raw_to_obsidian.py`，纯读 DB）
- 正文回填脚本（`backfill_story_body.py`）
- WebSocket 实时价格（可选）

---

## 2026-04-16 — 移除 AI 处理模块

### 背景

项目从「AI 新闻分析系统」重构为「纯数据采集监控系统」，移除所有 AI 相关处理逻辑（翻译、多空分析、情绪汇总），保留核心的新闻抓取、存储、Web 展示功能。

---

### 删除的模块/目录

| 目录/文件 | 说明 |
|-----------|------|
| `agents/` | 整个目录，含 4 个 AI Agent（TranslationAgent, FilterAgent, AnalysisAgent, SummaryAgent） |
| `core/rate_limiter.py` | 仅被 AI Agents 使用的令牌桶限速器 |

---

### 修改的文件

#### 数据库层

| 文件 | 改动 |
|------|------|
| `db/models.py` | 移除 `FilterResult`、`AnalysisResult`、`SummaryResult` dataclass；移除 `title_zh`、`short_desc_zh` 字段 |
| `db/database.py` | DDL 移除 `news_analysis` 表、`market_summaries` 表；移除 `title_zh`/`short_desc_zh` 列迁移 |
| `db/repository.py` | 移除所有 AI 分析/翻译相关方法（`save_filter_result`、`save_analysis`、`get_recent_analyses`、`count_sentiments`、`save_summary`、`get_latest_summary`、`save_translation`、`get_untranslated_en`）；保留 `save_news_batch`、`save_story_body`、`filter_new_ids`、`query_raw_news` |

#### 业务逻辑层

| 文件 | 改动 |
|------|------|
| `pipeline/orchestrator.py` | 移除 TranslationAgent、FilterAgent、AnalysisAgent；移除 AI 开关读取；移除翻译和 AI 分析任务；仅保留新闻抓取→存储→展示流程 |
| `pipeline/scheduler.py` | 移除 SummaryAgent；移除定时汇总循环（`_summary_loop`） |
| `display/console.py` | 移除 `show_analysis`、`show_summary`、`show_query_results`、`show_filtered`、`show_latest_summary` 方法；保留 `show_raw`、`show_raw_list` |
| `config/settings.py` | 移除所有 MiniMax API 配置（`MINIMAX_API_KEY`、`MINIMAX_BASE_URL`、`MINIMAX_MODEL` 等）；移除 AI 相关开关（`ENABLE_AI_ANALYSIS`、`ENABLE_TRANSLATION` 等）；移除 Token 预算配置 |

#### 入口层

| 文件 | 改动 |
|------|------|
| `run.py` | 移除 `--sentiment`、`--summary` 查询参数；移除 `show_latest_summary` 调用；重命名标题为 `TradingView News Monitor` |

#### Web 层

| 文件 | 改动 |
|------|------|
| `web/server.py` | 移除 `/api/settings`（AI 开关 API）；移除 `title_zh`/`short_desc_zh` 在 `/api/stats`、`/api/news`、`/api/news_detail`、`/api/analytics` 的返回；移除翻译进度统计 |
| `web/index.html` | 移除设置面板（AI 翻译/AI 分析开关）；移除统计栏翻译进度（`en_total`/`en_translated`）；移除新闻卡片中文标题显示（`title_zh`）；移除弹窗中文标题行；移除 `loadSettings`、`toggleSetting` JS 函数 |
| `web/analytics.html` | 移除「AI Translation Progress」整个板块（第4行区块）；移除 `renderTranslation`、`loadSettings` JS 函数；移除进度条 CSS 样式 |

#### 同步脚本

| 文件 | 改动 |
|------|------|
| `scripts/sync_raw_to_obsidian.py` | 移除 `title_zh` frontmatter 字段；移除中文标题行显示；SQL 查询不再读取 `title_zh` |

#### 配置与文档

| 文件 | 改动 |
|------|------|
| `.env.example` | 移除 `MINIMAX_API_KEY`、`ENABLE_AI_ANALYSIS`、`ENABLE_TRANSLATION` |
| `README.md` | 全面重写，移除所有 AI 翻译/AI 分析相关内容；更新目录结构；更新架构图；移除 AI 相关 FAQ |
| `CHANGELOG.md` | 本文件 |

---

### 数据库清理

执行 `scripts/db_cleanup.py`，结果：

| 操作 | 状态 |
|------|------|
| 删除 `news_analysis` 表（12 条数据） | ✓ |
| 删除 `market_summaries` 表（0 条） | ✓ |
| 删除 `system_state.enable_translation` | ✓ |
| 删除 `system_state.enable_ai_analysis` | ✓ |

**保留的 `system_state` keys：** `last_poll_time`、`last_published_en`、`last_published_zh-Hans`

**`raw_news` 表：** 8275 条数据完整保留，`title_zh`/`short_desc_zh` 列仍存在于 schema 中但数据已全部为 NULL，代码层已完全不读写这两列。

---

### 保留的功能

- TradingView 新闻抓取（双语 en/zh-Hans 并发）
- 增量轮询（基于 `system_state` 时间戳）
- 新闻正文抓取（后台异步）
- SQLite 持久化存储
- 终端彩色展示（`show_raw`）
- Web 看板（`/`)
- 数据分析页（`/analytics`，已移除翻译进度板块）
- Obsidian 同步（`sync_raw_to_obsidian.py`）
- 正文回填脚本（`backfill_story_body.py`）
- WebSocket 实时价格（可选）

---

### 系统状态

```
当前表:
  raw_news       — 8275 条（核心数据）
  system_state   — 3 个 key（轮询状态）

系统运行模式: 纯数据采集监控（无 AI 处理）
```
