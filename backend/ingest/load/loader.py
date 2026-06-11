"""멱등 upsert 헬퍼.

모든 적재는 이 헬퍼를 거친다. UNIQUE 제약을 ON CONFLICT 키로 사용해
같은 데이터를 두 번 넣어도 행이 늘지 않는다(멱등성).

예)
    from backend.ingest.load.loader import upsert
    upsert(conn, "league_rule",
           rows=[{"league":"KBO","rule_key":"dh","rule_value":"yes"}],
           conflict_cols=["league","rule_key","valid_from_year"])
"""
from __future__ import annotations

import sqlite3
from typing import Iterable, Mapping, Sequence


def upsert(
    conn: sqlite3.Connection,
    table: str,
    rows: Iterable[Mapping[str, object]],
    conflict_cols: Sequence[str],
    update_cols: Sequence[str] | None = None,
) -> int:
    """rows 를 table 에 upsert. 적용된 행 수를 반환."""
    rows = list(rows)
    if not rows:
        return 0

    cols = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in cols)
    col_list = ", ".join(cols)

    if update_cols is None:
        update_cols = [c for c in cols if c not in conflict_cols]
    set_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
    conflict = ", ".join(conflict_cols)

    if set_clause:
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict}) DO UPDATE SET {set_clause}"
        )
    else:
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict}) DO NOTHING"
        )

    data = [tuple(row[c] for c in cols) for row in rows]
    conn.executemany(sql, data)
    conn.commit()
    return len(data)


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn
