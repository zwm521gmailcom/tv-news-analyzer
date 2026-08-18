#!/usr/bin/env python3
"""
将 tv_news_analyzer SQLite 同步为 Obsidian raw 新闻笔记

用法：
  python3 scripts/sync_raw_to_obsidian.py              # 全量同步
  python3 scripts/sync_raw_to_obsidian.py --limit 20   # 测试：只同步最新20条
  python3 scripts/sync_raw_to_obsidian.py --since 24   # 增量：最近24小时
"""
import argparse
import json
import pathlib
import re
import sqlite3
from datetime import datetime, timezone, timedelta

DB_PATH     = "/Users/weiminzhu/Downloads/项目/tv_news_analyzer/data/tv_news.db"
VAULT_PATH  = pathlib.Path("/Users/weiminzhu/Desktop/tvnews")

# ──────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────

def sanitize_filename(s: str) -> str:
    """移除 Obsidian 文件名不允许的字符，截断至 60 字符"""
    s = re.sub(r'[/\\:*?"<>|#\[\]\']', '-', s)
    s = re.sub(r'-+', '-', s).strip('-').strip()
    return s[:60] or 'unknown'


def parse_symbols(symbols_json: str) -> tuple[list, list]:
    """
    ["NYSE:JNJ", "NASDAQ:GOOG"] → (全符号列表, ticker列表)
    """
    try:
        raw = json.loads(symbols_json or '[]')
        if not isinstance(raw, list):
            return [], []
        tickers = [s.split(':')[-1] for s in raw if ':' in s]
        for s in raw:
            if ':' not in s:
                tickers.append(s)
        return raw, tickers
    except Exception:
        return [], []


# ──────────────────────────────────────────────────────────────────────
# Symbol stub 页
# ──────────────────────────────────────────────────────────────────────

def create_symbol_stub(ticker: str, full_symbol: str, market: str) -> None:
    """创建 symbol stub 页，已存在则跳过"""
    symbols_dir = VAULT_PATH / 'symbols'
    symbols_dir.mkdir(parents=True, exist_ok=True)
    filepath = symbols_dir / f'{sanitize_filename(ticker)}.md'

    if filepath.exists():
        return

    if ':' in full_symbol:
        exchange = full_symbol.split(':')[0]
    else:
        exchange = 'UNKNOWN'

    market = market or 'unknown'
    exchange_tag = exchange.lower()
    market_tag = market.lower()

    content = f'''---
type: symbol
ticker: "{ticker}"
exchange: "{exchange}"
full_symbol: "{full_symbol}"
market: {market}
tags:
  - symbol
  - market/{market_tag}
  - exchange/{exchange_tag}
---

# {ticker}

**交易所**：{exchange} ｜ **市场**：{market}

---

*此页由 sync 脚本自动创建。右侧 Backlinks 面板可查看所有相关新闻。*
'''
    filepath.write_text(content, encoding='utf-8')


# ──────────────────────────────────────────────────────────────────────
# Daily index
# ──────────────────────────────────────────────────────────────────────

def create_daily_index(date_str: str) -> None:
    """创建每日索引页，已存在则跳过"""
    daily_dir = VAULT_PATH / 'daily'
    daily_dir.mkdir(parents=True, exist_ok=True)
    filepath = daily_dir / f'{date_str}.md'

    if filepath.exists():
        return

    content = f'''---
date: {date_str}
tags:
  - daily
---

# {date_str}

```dataview
TABLE title, provider, market, urgency
FROM "raw/{date_str}"
SORT published DESC
```
'''
    filepath.write_text(content, encoding='utf-8')


def create_index() -> None:
    """创建 _index.md 总览入口，已存在则跳过"""
    filepath = VAULT_PATH / '_index.md'
    if filepath.exists():
        return

    content = '''---
type: index
tags:
  - index
---

# tvnews 知识库总览

> TradingView 新闻 → Obsidian 知识图谱

## 导航

- [[daily/]] — 每日新闻索引
- `raw/` — 原始新闻笔记（按日期分组）
- `symbols/` — 标的页面（图谱枢纽节点）

## 快速查询（需要 Dataview 插件）

### 今日新闻
```dataview
TABLE title, provider, market
FROM "raw"
WHERE date = date(today)
SORT published DESC
LIMIT 20
```

### 高权重新闻（urgency 3）
```dataview
TABLE title, provider, date
FROM "raw"
WHERE urgency = 3
SORT published DESC
LIMIT 20
```

### 加密市场新闻
```dataview
TABLE title, provider, date
FROM "raw"
WHERE market = "crypto"
SORT published DESC
LIMIT 20
```
'''
    filepath.write_text(content, encoding='utf-8')


# ──────────────────────────────────────────────────────────────────────
# Raw note 渲染
# ──────────────────────────────────────────────────────────────────────

def render_raw_note(row: dict) -> str:
    symbols, tickers = parse_symbols(row.get('symbols', '[]'))
    pub_dt = datetime.fromtimestamp(row['published'], tz=timezone.utc)
    date_str = pub_dt.strftime('%Y-%m-%d')
    pub_iso = pub_dt.strftime('%Y-%m-%dT%H:%M:%S')

    market = row.get('market') or 'unknown'
    lang = row.get('lang') or 'en'
    provider = row.get('provider') or ''
    urgency = row.get('urgency') or 1
    is_flash = bool(row.get('is_flash'))

    tags = ['news/raw', f'market/{market}', f'lang/{lang}']
    if provider:
        provider_tag = provider.lower().replace(' ', '-').replace(',', '').replace('.', '')
        tags.append(f'source/{provider_tag}')
    if urgency >= 3:
        tags.append('urgency/high')
    if is_flash:
        tags.append('flash')

    # Symbol wikilinks
    if tickers:
        symbol_links = ' '.join(f'[[symbols/{t}]]' for t in tickers)
    else:
        symbol_links = '—'

    title = row.get('title') or ''
    title_safe = title.replace('"', "'")
    body = (row.get('story_body') or '').strip()

    def yaml_list(items):
        if not items:
            return '  []\n'
        unique = list(dict.fromkeys(items))
        return '\n'.join(f'  - "{item}"' for item in unique) + '\n'

    fm_symbols = yaml_list(symbols)
    fm_tickers = yaml_list(tickers)
    fm_tags = '\n'.join(f'  - {t}' for t in tags)

    return f'''---
id: "{row['id'].replace('"', "'")}"
title: "{title_safe}"
date: {date_str}
published: "{pub_iso}"
provider: "{provider}"
market: {market}
urgency: {urgency}
is_flash: {"true" if is_flash else "false"}
lang: {lang}
symbols:
{fm_symbols}
tickers:
{fm_tickers}
tags:
{fm_tags}
---

# {title}

> **来源**：{provider or "未知"} ｜ **时间**：{pub_iso.replace("T", " ")} ｜ [[daily/{date_str}]]
**相关标的**：{symbol_links}

---

{body}
'''


# ──────────────────────────────────────────────────────────────────────
# 同步主逻辑
# ──────────────────────────────────────────────────────────────────────

def sync(limit=None, since_hours=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    query = """
        SELECT id, title, published, provider, market,
               urgency, is_flash, lang, symbols, story_body
        FROM raw_news
        WHERE 1=1
    """
    params = []

    if since_hours is not None:
        cutoff = int((datetime.now(timezone.utc) - timedelta(hours=since_hours)).timestamp())
        query += " AND published > ?"
        params.append(cutoff)

    query += " ORDER BY published DESC"

    if limit is not None:
        query += f" LIMIT {limit}"

    rows = conn.execute(query, params).fetchall()
    total = len(rows)
    created = 0
    skipped = 0
    symbol_stubs_done = set()
    daily_done = set()

    print(f"共 {total} 条待处理...")

    for i, row in enumerate(rows, 1):
        row = dict(row)
        pub_dt = datetime.fromtimestamp(row['published'], tz=timezone.utc)
        date_str = pub_dt.strftime('%Y-%m-%d')

        symbols, tickers = parse_symbols(row.get('symbols', '[]'))
        prefix = tickers[0] if tickers else 'news'
        slug = sanitize_filename(row['title'])
        filename = f'{sanitize_filename(prefix)}-{slug}.md'

        market = row.get('market') or 'unknown'
        folder = VAULT_PATH / 'raw' / date_str / market
        folder.mkdir(parents=True, exist_ok=True)
        filepath = folder / filename

        if filepath.exists():
            skipped += 1
        else:
            filepath.write_text(render_raw_note(row), encoding='utf-8')
            created += 1

        # 创建 symbol stub 页
        for full_sym, tick in zip(symbols, tickers):
            if tick not in symbol_stubs_done:
                create_symbol_stub(tick, full_sym, row.get('market', 'unknown'))
                symbol_stubs_done.add(tick)

        # 创建 daily 索引页
        if date_str not in daily_done:
            create_daily_index(date_str)
            daily_done.add(date_str)

        if i % 200 == 0 or i == total:
            print(f'  进度 {i}/{total}  新建={created}  跳过={skipped}  symbols={len(symbol_stubs_done)}')

    create_index()

    print(f'\n✅ 完成：新建 {created} 条，跳过 {skipped} 条')
    print(f'   Symbol stubs：{len(symbol_stubs_done)} 个')
    print(f'   Daily 索引：{len(daily_done)} 天')
    print(f'   Vault 路径：{VAULT_PATH}')
    conn.close()


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='将 tv_news_analyzer SQLite 同步为 Obsidian 笔记'
    )
    parser.add_argument('--limit', type=int, default=None,
                        help='只处理最新 N 条（测试用）')
    parser.add_argument('--since', type=float, default=None,
                        help='只处理最近 N 小时的新闻（增量同步）')
    args = parser.parse_args()

    sync(
        limit=args.limit,
        since_hours=args.since,
    )


if __name__ == '__main__':
    main()
