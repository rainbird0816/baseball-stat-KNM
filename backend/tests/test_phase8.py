"""Phase 8 — 당일 증분 파이프라인 검증.

daily.run 이 기존 백필과 같은 멱등 경로로 '추가 날짜'의 종료 경기를 증분하는지,
재실행해도 행이 늘지 않는지(멱등) 본다. 원본 JSON 은 data/raw/statsapi/ 캐시 사용.

실행:
    python -m backend.tests.test_phase8
    pytest backend/tests/test_phase8.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.ingest import daily
from backend.ingest.sources import mlb_statsapi
from backend.ingest.sources.mlb_lahman import load as mlb_load

DB = Path(__file__).resolve().parents[2] / "data" / "baseball.db"
BASE_DATE = "2022-04-15"          # phase2 기본 슬라이스
INCR_DATES = ("2022-04-16", "2022-04-17")  # daily 가 증분하는 날짜


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute("PRAGMA foreign_keys = ON")
    c.row_factory = sqlite3.Row
    c.text_factory = str
    return c


def _game_count(c, date=None) -> int:
    if date:
        return c.execute(
            "SELECT count(*) FROM game WHERE game_date=?", (date,)
        ).fetchone()[0]
    return c.execute("SELECT count(*) FROM game").fetchone()[0]


def _ensure_loaded() -> None:
    c = _conn()
    has_ts = c.execute(
        """SELECT 1 FROM team_season ts JOIN franchise f ON f.id=ts.franchise_id
           JOIN season se ON se.id=ts.season_id
           WHERE f.league='MLB' AND se.year=2022 LIMIT 1"""
    ).fetchone() is not None
    g_base = _game_count(c, BASE_DATE)
    g_incr = _game_count(c, INCR_DATES[0])
    c.close()
    if not has_ts:
        mlb_load(2022)
    if g_base == 0:
        mlb_statsapi.backfill(BASE_DATE, BASE_DATE)
    if g_incr == 0:
        daily.run(INCR_DATES[0], INCR_DATES[1])  # 증분(캐시 사용)


def test_daily_added_new_days():
    """daily 가 기본 슬라이스 외의 날짜 경기를 증분했다(각 날짜 종료경기 존재)."""
    _ensure_loaded()
    c = _conn()
    for d in INCR_DATES:
        n = _game_count(c, d)
        assert n == 15, f"{d} game {n} (15 기대)"
    # 기본 슬라이스도 그대로
    assert _game_count(c, BASE_DATE) == 15
    c.close()


def test_daily_only_final_regular_statsapi():
    """증분 경기는 정규시즌·종료·source='statsapi'."""
    _ensure_loaded()
    c = _conn()
    rows = c.execute(
        "SELECT game_type, status, source FROM game WHERE game_date IN (?,?)",
        INCR_DATES,
    ).fetchall()
    c.close()
    assert rows, "증분 경기 없음"
    for r in rows:
        assert r["game_type"] == "regular", dict(r)
        assert r["status"] in ("final", "tie"), dict(r)
        assert r["source"] == "statsapi", dict(r)


def test_daily_idempotent():
    """같은 날짜 범위를 daily 재실행해도 game/batting/pitching 행 수 불변."""
    _ensure_loaded()
    c = _conn()
    before = (
        _game_count(c),
        c.execute("SELECT count(*) FROM player_batting_game").fetchone()[0],
        c.execute("SELECT count(*) FROM player_pitching_game").fetchone()[0],
    )
    c.close()

    daily.run(INCR_DATES[0], INCR_DATES[1])  # 재실행

    c = _conn()
    after = (
        _game_count(c),
        c.execute("SELECT count(*) FROM player_batting_game").fetchone()[0],
        c.execute("SELECT count(*) FROM player_pitching_game").fetchone()[0],
    )
    fk = c.execute("PRAGMA foreign_key_check").fetchall()
    c.close()
    assert before == after, f"멱등성 위반: {before} -> {after}"
    assert not fk, f"FK 위반: {fk}"


if __name__ == "__main__":
    test_daily_added_new_days()
    test_daily_only_final_regular_statsapi()
    test_daily_idempotent()
    print("all phase8 tests passed")
