#!/usr/bin/env python3
"""
根据 raw_json 回填可推导字段：
- market
- sector
- country
- corp_activity

说明：
- short_desc 不在历史 raw_json 中，无法回填
- corp_activity 通过标题 / 正文 / path 启发式推断
"""
import argparse
import json
import os
import sqlite3
import sys
from typing import Iterable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from core.raw_json_fields import derive_fields_from_raw_item


def _is_missing(value: object) -> bool:
    return value is None or value == "" or value == "unknown"


def _iter_rows(conn: sqlite3.Connection, limit: int = 0) -> Iterable[sqlite3.Row]:
    sql = """
        SELECT id, title, provider, market, sector, country, corp_activity,
               story_body, raw_json
        FROM raw_news
        ORDER BY published DESC
    """
    if limit and limit > 0:
        sql += " LIMIT ?"
        cur = conn.execute(sql, (limit,))
    else:
        cur = conn.execute(sql)
    yield from cur.fetchall()


def backfill_raw_fields(
    db_path: str | None = None,
    limit: int = 0,
    dry_run: bool = False,
    overwrite: bool = False,
) -> int:
    """
    回填 raw_news 里可从 raw_json 推导的字段。

    返回实际更新的行数。
    """
    db_path = db_path or settings.DB_PATH
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    updated_rows = 0
    scanned_rows = 0
    updated_market = 0
    updated_sector = 0
    updated_country = 0
    updated_corp_activity = 0

    try:
        for row in _iter_rows(conn, limit=limit):
            scanned_rows += 1
            try:
                raw_item = json.loads(row["raw_json"])
            except Exception:
                continue

            derived = derive_fields_from_raw_item(raw_item, story_body=row["story_body"] or "")
            patch = {}

            if overwrite:
                patch["market"] = derived["market"]
            elif _is_missing(row["market"]) and not _is_missing(derived["market"]):
                patch["market"] = derived["market"]
            if overwrite:
                patch["sector"] = derived["sector"]
            elif _is_missing(row["sector"]) and not _is_missing(derived["sector"]):
                patch["sector"] = derived["sector"]
            if overwrite:
                patch["country"] = derived["country"]
            elif _is_missing(row["country"]) and not _is_missing(derived["country"]):
                patch["country"] = derived["country"]
            if overwrite:
                patch["corp_activity"] = derived["corp_activity"]
            elif _is_missing(row["corp_activity"]) and not _is_missing(derived["corp_activity"]):
                patch["corp_activity"] = derived["corp_activity"]

            if not patch:
                continue

            if not dry_run:
                if overwrite:
                    conn.execute(
                        """
                        UPDATE raw_news
                        SET market = ?,
                            sector = ?,
                            country = ?,
                            corp_activity = ?
                        WHERE id = ?
                        """,
                        (
                            patch.get("market"),
                            patch.get("sector"),
                            patch.get("country"),
                            patch.get("corp_activity"),
                            row["id"],
                        ),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE raw_news
                        SET market = COALESCE(?, market),
                            sector = COALESCE(?, sector),
                            country = COALESCE(?, country),
                            corp_activity = COALESCE(?, corp_activity)
                        WHERE id = ?
                        """,
                        (
                            patch.get("market"),
                            patch.get("sector"),
                            patch.get("country"),
                            patch.get("corp_activity"),
                            row["id"],
                        ),
                    )
            updated_rows += 1
            if "market" in patch:
                updated_market += 1
            if "sector" in patch:
                updated_sector += 1
            if "country" in patch:
                updated_country += 1
            if "corp_activity" in patch:
                updated_corp_activity += 1

        if not dry_run:
            conn.commit()
    finally:
        conn.close()

    print(
        f"[BackfillRaw] scanned={scanned_rows} updated={updated_rows} "
        f"market={updated_market} sector={updated_sector} country={updated_country} "
        f"corp_activity={updated_corp_activity}"
    )
    return updated_rows


def main():
    parser = argparse.ArgumentParser(description="回填 raw_news 的可推导字段")
    parser.add_argument("--db", default=settings.DB_PATH, help="SQLite 数据库路径")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少条，0 表示全部")
    parser.add_argument("--dry-run", action="store_true", help="只扫描不写入")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已有值，执行全量更新")
    args = parser.parse_args()
    backfill_raw_fields(
        db_path=args.db,
        limit=args.limit,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    main()
