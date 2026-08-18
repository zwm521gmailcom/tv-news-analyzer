#!/usr/bin/env python3
"""
从 DB 同步新闻到 Obsidian 笔记
- 按日期组织新闻
- 创建日期文件夹和索引笔记
- 发现新 Symbol 时自动补充 Symbols 笔记
"""
import sqlite3
import json
import subprocess
import os
from datetime import datetime
from collections import defaultdict

DB_PATH = "/Users/weiminzhu/Downloads/项目/tv_news_analyzer/data/tv_news.db"
VAULT_NAME = ""

MARKETS = ["crypto", "stock", "forex", "futures", "index", "economic"]
MARKET_COLORS = {
    "crypto": "🟠",
    "stock": "🔵",
    "forex": "🟢",
    "futures": "🟡",
    "index": "🟣",
    "economic": "⚪",
}


def obsidian_create(path, content):
    """调用 obsidian CLI 创建笔记"""
    path = path.replace("\\", "\\\\")
    cmd = [
        "obsidian", "create",
        f"path={path}",
        f"content={content}",
        "silent"
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return True
    except Exception as e:
        print(f"  ⚠️ 创建失败 {path}: {e}")
        return False


def parse_symbols(symbols_json):
    """解析 symbols JSON 列表"""
    if not symbols_json or symbols_json == "[]":
        return []
    try:
        return json.loads(symbols_json)
    except:
        return []


def format_symbol_id(symbol):
    """将 BINANCE:BTCUSD 转为 Symbol-BINANCE-BTCUSD"""
    if ":" in symbol:
        exchange, ticker = symbol.split(":", 1)
        ticker = ticker.replace("!", "_exc_").replace(".", "_dot_")
        return f"Symbol-{exchange}-{ticker}"
    return f"Symbol-{symbol}"


def normalize_market(market):
    """标准化市场名称"""
    if market in MARKETS:
        return market
    return "unknown"


def timestamp_to_datetime(ts):
    """时间戳转日期时间"""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def timestamp_to_date_only(ts):
    """时间戳转日期"""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def safe_filename(s):
    """处理文件名非法字符"""
    return s.replace(":", "_").replace("/", "_").replace("\\", "_").replace("|", "_")[:60]


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 获取所有新闻，按时间倒序
    cur.execute("""
        SELECT id, title, short_desc, provider, market, symbols, lang, published, story_body
        FROM raw_news
        ORDER BY published DESC
        LIMIT 500
    """)
    news_list = cur.fetchall()

    print(f"📰 开始同步 {len(news_list)} 条新闻到 Obsidian...")

    # 按日期分组
    daily_news = defaultdict(list)
    all_symbols = set()

    for row in news_list:
        news_date = timestamp_to_date_only(row["published"])
        symbols = parse_symbols(row["symbols"] or "[]")
        all_symbols.update(symbols)
        daily_news[news_date].append(row)

    # 创建日期文件夹和索引笔记
    created_days = 0
    total_news_links = 0

    for date_str in sorted(daily_news.keys(), reverse=True):
        news_items = daily_news[date_str]

        # 构建日期索引笔记内容
        index_lines = [
            "---",
            f"date: {date_str}",
            "tags:",
            "  - #daily",
            "---",
            "",
            f"# 📅 {date_str} 新闻索引",
            "",
            f"**新闻数量:** {len(news_items)}",
            "",
            "---",
            "",
            "## 📰 新闻列表",
            "",
        ]

        # 按市场分组显示
        by_market = defaultdict(list)
        for row in news_items:
            by_market[row["market"]].append(row)

        for market in ["stock", "crypto", "forex", "futures", "index", "economic", "unknown"]:
            if market not in by_market:
                continue
            market_icon = MARKET_COLORS.get(market, "⚪")
            index_lines.append(f"\n### {market_icon} {market.upper()}")
            index_lines.append("")

            for row in by_market[market]:
                safe_id = safe_filename(row["id"])
                title = row["title"] or "无标题"
                time_str = timestamp_to_datetime(row["published"]).split(" ")[1]
                lang_tag = "🇺🇸" if row["lang"] == "en" else "🇨🇳"

                index_lines.append(f"- {time_str} {lang_tag} [[News/{date_str}/{safe_id}|{title[:40]}...]]")

        # 创建日期文件夹的索引笔记
        index_content = "\\n".join(index_lines)
        index_path = f"Daily/{date_str}/{date_str}.md"

        if obsidian_create(index_path, index_content):
            created_days += 1
            total_news_links += len(news_items)
            print(f"  ✓ 已创建日期索引: {date_str} ({len(news_items)} 条)")

    print(f"\n📊 日期索引创建完成:")
    print(f"  - 日期文件夹: {created_days}")
    print(f"  - 新闻链接: {total_news_links}")

    # 创建新闻笔记（更新路径，包含日期）
    print(f"\n📰 创建新闻笔记...")
    created_news = 0
    skipped_news = 0

    for row in news_list:
        news_id = row["id"]
        title = row["title"] or "无标题"
        short_desc = row["short_desc"] or ""
        provider = row["provider"] or "Unknown"
        market = normalize_market(row["market"])
        symbols_json = row["symbols"] or "[]"
        lang = row["lang"] or "en"
        published = timestamp_to_datetime(row["published"])
        story_body = row["story_body"] or ""
        news_date = timestamp_to_date_only(row["published"])
        symbols = parse_symbols(symbols_json)

        safe_id = safe_filename(news_id)
        news_path = f"News/{news_date}/{safe_id}.md"

        market_icon = MARKET_COLORS.get(market, "⚪")
        lang_tag = "🇺🇸" if lang == "en" else "🇨🇳"

        content_lines = [
            "---",
            f"title: {title}",
            f"date: {news_date}",
            f"provider: {provider}",
            f"market: {market}",
            f"lang: {lang}",
            f"symbols: {symbols_json}",
            "tags:",
            f"  - #news",
            f"  - #{market}",
            "---",
            "",
            f"# {title}",
            "",
            f"**日期:** [[Daily/{news_date}/{news_date}|{news_date}]]",
            f"**来源:** [[Providers/Provider-{provider.replace(' ', '')}]]",
            f"**市场:** {market_icon} [[Markets/Market-{market}]]",
            f"**语言:** {lang_tag} {lang}",
            f"**时间:** {published}",
        ]

        if symbols:
            symbol_links = [f"[[Symbols/{format_symbol_id(s)}]]" for s in symbols]
            content_lines.append(f"**关联:** {', '.join(symbol_links)}")

        content_lines.extend([
            "",
            "---",
            "",
            "## 摘要",
            short_desc[:500] if short_desc else "无",
            "",
        ])

        if story_body and len(story_body) > 10:
            content_lines.extend([
                "---",
                "",
                "## 正文",
                story_body[:2000] + ("..." if len(story_body) > 2000 else ""),
            ])

        content_lines.extend([
            "",
            "---",
            f"**News ID:** `{news_id}`",
        ])

        content = "\\n".join(content_lines)

        if obsidian_create(news_path, content):
            created_news += 1
            if created_news % 100 == 0:
                print(f"  ✓ 已创建 {created_news} 条新闻笔记...")
        else:
            skipped_news += 1

    print(f"\n📊 新闻笔记创建完成:")
    print(f"  - 创建: {created_news}")
    print(f"  - 跳过: {skipped_news}")

    # 补充新 Symbols
    if all_symbols:
        print(f"\n🔗 补充 Symbols 笔记...")
        created_symbols = 0
        for sym in all_symbols:
            sym_id = format_symbol_id(sym)
            sym_content = f"""# {sym_id}

交易所/品种: {sym}

## 所属市场
[[Markets/Market-stock]]

## 关联新闻
自动从 TradingView 新闻数据提取

## 标签
#symbol #stock
"""
            path = f"Symbols/{sym_id}.md"
            if obsidian_create(path, sym_content):
                created_symbols += 1
                if created_symbols % 50 == 0:
                    print(f"  ✓ 已补充 {created_symbols} 个 Symbols...")

        print(f"  - 补充 Symbols: {created_symbols}")

    conn.close()
    print("\n✅ 同步完成!")


if __name__ == "__main__":
    main()
