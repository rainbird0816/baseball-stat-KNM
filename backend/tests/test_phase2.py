"""Phase 2 — MLB 경기 단위(T2) 적재 검증.

game / player_batting_game / player_pitching_game 이 StatsAPI 슬라이스로
올바르게 적재됐는지 본다. init_db --fresh 는 팩트를 비우므로, 비어 있으면
캐시된 원본(Lahman CSV + StatsAPI JSON)으로 2022 시즌 + 2022-04-15 슬라이스를
스스로 적재한 뒤 검증한다(원본은 data/raw/ 에 캐시되어 있어야 함).

실행:
    python -m backend.tests.test_phase2
    pytest backend/tests/test_phase2.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.ingest.sources.mlb_lahman import load as load_season
from backend.ingest.sources.mlb_statsapi import backfill

DB = Path(__file__).resolve().parents[2] / "data" / "baseball.db"
SEASON = 2022
SLICE_DATE = "2022-04-15"  # 전 경기 슬레이트(15경기)

GAME_TABLES = ("game", "player_batting_game", "player_pitching_game")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute("PRAGMA foreign_keys = ON")
    c.row_factory = sqlite3.Row
    return c


def _counts(c: sqlite3.Connection) -> dict[str, int]:
    return {t: c.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in GAME_TABLES}


def _ensure_loaded() -> None:
    c = _conn()
    n_ts = c.execute("SELECT count(*) FROM team_season").fetchone()[0]
    n_game = c.execute("SELECT count(*) FROM game").fetchone()[0]
    c.close()
    if n_ts == 0:
        load_season(SEASON)          # Phase 1 차원/시즌 스탯 (team_season, person)
    if n_game == 0:
        backfill(SLICE_DATE, SLICE_DATE)  # Phase 2 경기 슬라이스 (캐시된 JSON)


def test_slice_game_count():
    """2022-04-15 정규시즌 Final 경기 15개."""
    _ensure_loaded()
    c = _conn()
    n = c.execute(
        "SELECT count(*) FROM game WHERE league='MLB' AND game_date=?", (SLICE_DATE,)
    ).fetchone()[0]
    c.close()
    assert n == 15, f"game {n}개 (15 기대)"


def test_sample_game_score():
    """샘플 경기: 메츠 10 : 3 다이아몬드백스 (Citi Field)."""
    _ensure_loaded()
    c = _conn()
    row = c.execute(
        """
        SELECT hts.team_name AS home, ats.team_name AS away,
               g.home_score, g.away_score
        FROM game g
        JOIN team_season hts ON hts.id = g.home_ts_id
        JOIN team_season ats ON ats.id = g.away_ts_id
        WHERE g.game_date = ? AND hts.team_name LIKE '%Mets%'
        """,
        (SLICE_DATE,),
    ).fetchone()
    c.close()
    assert row is not None, "메츠 경기 없음"
    assert row["home_score"] == 10 and row["away_score"] == 3, dict(row)
    assert "Diamondbacks" in row["away"], dict(row)


def test_one_decision_pair_per_game():
    """각 경기에 승리/패전 투수 정확히 1명씩 → 슬라이스 전체 W 15, L 15."""
    _ensure_loaded()
    c = _conn()
    w = c.execute(
        """
        SELECT count(*) FROM player_pitching_game pg
        JOIN game g ON g.id = pg.game_id
        WHERE g.game_date = ? AND pg.decision = 'W'
        """,
        (SLICE_DATE,),
    ).fetchone()[0]
    l = c.execute(
        """
        SELECT count(*) FROM player_pitching_game pg
        JOIN game g ON g.id = pg.game_id
        WHERE g.game_date = ? AND pg.decision = 'L'
        """,
        (SLICE_DATE,),
    ).fetchone()[0]
    c.close()
    assert w == 15, f"승리투수 {w} (15 기대)"
    assert l == 15, f"패전투수 {l} (15 기대)"


def test_ip_outs_integer_and_sane():
    """이닝은 아웃 정수 — 음수 없고 환산 소수부는 0/1/2."""
    _ensure_loaded()
    c = _conn()
    rows = c.execute(
        "SELECT ip_outs FROM player_pitching_game WHERE ip_outs IS NOT NULL"
    ).fetchall()
    c.close()
    assert rows, "투구 라인 없음"
    for (outs,) in rows:
        assert outs >= 0 and outs % 3 in (0, 1, 2), f"비정상 ip_outs={outs}"


def test_batting_line_consistency():
    """타격 라인 정합: pa>=ab>=h>=hr (모든 행)."""
    _ensure_loaded()
    c = _conn()
    rows = c.execute(
        "SELECT pa, ab, h, hr FROM player_batting_game"
    ).fetchall()
    c.close()
    assert rows, "타격 라인 없음"
    for r in rows:
        pa, ab, h, hr = (r["pa"] or 0), (r["ab"] or 0), (r["h"] or 0), (r["hr"] or 0)
        assert pa >= ab >= h >= hr, f"라인 비정합 pa={pa} ab={ab} h={h} hr={hr}"


def test_provenance_and_person_links():
    """source='statsapi' provenance + mlbam 인물 연결(외래키 무결)."""
    _ensure_loaded()
    c = _conn()
    bad_src = c.execute(
        "SELECT count(*) FROM game WHERE game_date=? AND source IS NOT 'statsapi'",
        (SLICE_DATE,),
    ).fetchone()[0]
    fk = c.execute("PRAGMA foreign_key_check").fetchall()
    mlbam = c.execute(
        "SELECT count(*) FROM person_external_id WHERE source='mlbam'"
    ).fetchone()[0]
    c.close()
    assert bad_src == 0, f"source!='statsapi' {bad_src}건"
    assert not fk, f"FK 위반: {fk}"
    assert mlbam >= 300, f"mlbam external_id {mlbam}개 (300+ 기대)"


def test_idempotent_rebackfill():
    """같은 슬라이스 재적재해도 game/배팅/투구 행 수 불변(멱등)."""
    _ensure_loaded()
    c = _conn()
    before = _counts(c)
    c.close()

    backfill(SLICE_DATE, SLICE_DATE)  # 재실행

    c = _conn()
    after = _counts(c)
    c.close()
    assert before == after, f"멱등성 위반: {before} -> {after}"


if __name__ == "__main__":
    test_slice_game_count()
    test_sample_game_score()
    test_one_decision_pair_per_game()
    test_ip_outs_integer_and_sane()
    test_batting_line_consistency()
    test_provenance_and_person_links()
    test_idempotent_rebackfill()
    print("all phase2 tests passed")
