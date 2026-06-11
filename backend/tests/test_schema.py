"""스키마/시드 검증 테스트.

실행:
    python -m backend.tests.test_schema     # pytest 없이도 동작
    pytest backend/tests/
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data" / "baseball.db"

EXPECTED_TABLES = {
    "organization", "franchise", "season", "park", "team_season",
    "person", "person_external_id", "stint",
    "batting_season", "pitching_season", "fielding_season",
    "game", "player_batting_game", "player_pitching_game",
    "award_share", "postseason_series", "postseason_game",
    "league_rule", "team_logo",
}


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute("PRAGMA foreign_keys = ON")
    return c


def test_all_tables_exist():
    c = _conn()
    have = {
        r[0]
        for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    missing = EXPECTED_TABLES - have
    assert not missing, f"누락 테이블: {missing}"
    c.close()


def test_foreign_keys_clean():
    c = _conn()
    problems = c.execute("PRAGMA foreign_key_check").fetchall()
    assert not problems, f"FK 위반: {problems}"
    c.close()


def test_seed_league_rules():
    c = _conn()
    dh = c.execute(
        "SELECT rule_value FROM league_rule WHERE league='KBO' AND rule_key='dh'"
    ).fetchone()
    assert dh and dh[0] == "yes"
    c.close()


def test_seed_kbo_franchises():
    c = _conn()
    n = c.execute("SELECT count(*) FROM franchise WHERE league='KBO'").fetchone()[0]
    assert n >= 10, f"KBO 프랜차이즈 {n}개 (10+ 기대)"
    c.close()


if __name__ == "__main__":
    test_all_tables_exist()
    test_foreign_keys_clean()
    test_seed_league_rules()
    test_seed_kbo_franchises()
    print("all schema tests passed")
