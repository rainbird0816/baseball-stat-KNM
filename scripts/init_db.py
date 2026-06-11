"""마이그레이션 적용기.

backend/migrations/ 의 *.sql 을 파일명 순서대로 baseball.db 에 적용한다.
멱등(idempotent): 모든 DDL 이 IF NOT EXISTS / INSERT OR IGNORE 라 재실행해도 안전.
시드(league_rule 등 OR IGNORE 아닌 INSERT)는 schema_migrations 로 1회만 적용.

사용:
    python scripts/init_db.py                 # data/baseball.db 생성/갱신
    python scripts/init_db.py --fresh         # 기존 DB 삭제 후 새로 생성
    python scripts/init_db.py --db path.db
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "backend" / "migrations"
DEFAULT_DB = ROOT / "data" / "baseball.db"


def applied_set(conn: sqlite3.Connection) -> set[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  filename TEXT PRIMARY KEY,"
        "  applied_at TEXT DEFAULT (datetime('now'))"
        ")"
    )
    return {r[0] for r in conn.execute("SELECT filename FROM schema_migrations")}


def apply_migrations(db_path: Path, fresh: bool = False) -> None:
    if fresh and db_path.exists():
        db_path.unlink()
        print(f"removed existing {db_path}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")

    done = applied_set(conn)
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise SystemExit(f"no .sql found in {MIGRATIONS_DIR}")

    for f in files:
        if f.name in done:
            print(f"skip  {f.name} (already applied)")
            continue
        sql = f.read_text(encoding="utf-8")
        try:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations(filename) VALUES (?)", (f.name,)
            )
            conn.commit()
            print(f"apply {f.name}")
        except sqlite3.Error as e:
            conn.rollback()
            raise SystemExit(f"FAILED {f.name}: {e}")

    # 요약
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    print(f"\nOK — {len(tables)} tables: {', '.join(tables)}")
    conn.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--fresh", action="store_true")
    args = p.parse_args()
    apply_migrations(Path(args.db), fresh=args.fresh)
