"""Phase 6 — 우승 시리즈 & 보조 데이터 검증.

월드시리즈/일본시리즈/한국시리즈(우승 결정전) + MVP, award_share 가 적재됐는지 본다.
init_db --fresh 는 팩트를 비우므로, postseason_series 가 비어 있으면 전제 데이터
(MLB 2022, NPB 2021·2022, KBO 2024)를 적재한 뒤 postseason.load() 로 채우고 검증한다.

실행:
    python -m backend.tests.test_phase6
    pytest backend/tests/test_phase6.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.ingest.sources import postseason
from backend.ingest.sources.kbo_official import backfill as kbo_backfill
from backend.ingest.sources.mlb_lahman import load as mlb_load
from backend.ingest.sources.npb_official import backfill as npb_backfill

DB = Path(__file__).resolve().parents[2] / "data" / "baseball.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute("PRAGMA foreign_keys = ON")
    c.row_factory = sqlite3.Row
    c.text_factory = str
    return c


def _has_season(c: sqlite3.Connection, league: str, year: int) -> bool:
    return c.execute(
        """SELECT 1 FROM team_season ts JOIN franchise f ON f.id=ts.franchise_id
           JOIN season se ON se.id=ts.season_id
           WHERE f.league=? AND se.year=? LIMIT 1""",
        (league, year),
    ).fetchone() is not None


def _ensure_loaded() -> None:
    c = _conn()
    n = c.execute("SELECT count(*) FROM postseason_series").fetchone()[0]
    need = {
        ("MLB", 2022): _has_season(c, "MLB", 2022),
        ("NPB", 2021): _has_season(c, "NPB", 2021),
        ("NPB", 2022): _has_season(c, "NPB", 2022),
        ("KBO", 2024): _has_season(c, "KBO", 2024),
    }
    c.close()
    if n > 0:
        return
    if not need[("MLB", 2022)]:
        mlb_load(2022)
    if not need[("NPB", 2021)]:
        npb_backfill(2021)
    if not need[("NPB", 2022)]:
        npb_backfill(2022)
    if not need[("KBO", 2024)]:
        kbo_backfill(2024)
    postseason.download()
    postseason.load()


def _championship(c, league, round_, year):
    return c.execute(
        """SELECT ps.wins, ps.losses, ps.ties, ps.is_championship,
                  fw.code AS win, fl.code AS lose,
                  pn.name_native AS mvp_native, pn.name_roman AS mvp_roman
           FROM postseason_series ps JOIN season se ON se.id=ps.season_id
           LEFT JOIN team_season tw ON tw.id=ps.winner_ts_id
           LEFT JOIN franchise fw ON fw.id=tw.franchise_id
           LEFT JOIN team_season tl ON tl.id=ps.loser_ts_id
           LEFT JOIN franchise fl ON fl.id=tl.franchise_id
           LEFT JOIN person pn ON pn.id=ps.mvp_person_id
           WHERE ps.league=? AND ps.round=? AND se.year=?""",
        (league, round_, year),
    ).fetchone()


def test_championships_present():
    """우승 결정전(is_championship=1) — MLB 다연도 백필 후 다수 + NPB×2/KBO×1 존재.

    과거엔 MLB 2022 만 적재돼 정확히 4개였으나, mlb_lahman.backfill_teams 로
    team_season 을 전 연도로 백필하면서 MLB World Series 가 다수 적재된다.
    따라서 '정확히 4개'가 아니라 '리그별 우승 결정전이 모두 존재 + MLB 다수'로 검증한다.
    """
    _ensure_loaded()
    c = _conn()
    total = c.execute(
        "SELECT count(*) FROM postseason_series WHERE is_championship=1"
    ).fetchone()[0]
    by_lg = {
        r["league"]: r["n"]
        for r in c.execute(
            "SELECT league, count(*) n FROM postseason_series "
            "WHERE is_championship=1 GROUP BY league"
        )
    }
    c.close()
    assert total >= 4, f"우승 결정전 {total}개 (4+ 기대)"
    # MLB 는 다연도 백필 시 다수(WS), 단일 시즌만 적재됐다면 최소 1.
    assert by_lg.get("MLB", 0) >= 1, f"MLB 우승 결정전 없음: {by_lg}"
    assert by_lg.get("NPB", 0) >= 2, f"NPB 우승 결정전 부족: {by_lg}"
    assert by_lg.get("KBO", 0) >= 1, f"KBO 우승 결정전 없음: {by_lg}"


def test_mlb_world_series_2022():
    """MLB 2022 WS: HOU가 PHI를 4-2로, MVP Jeremy Pena."""
    _ensure_loaded()
    c = _conn()
    r = _championship(c, "MLB", "WorldSeries", 2022)
    c.close()
    assert r is not None, "MLB 2022 WorldSeries 없음"
    assert r["is_championship"] == 1
    assert (r["win"], r["lose"]) == ("HOU", "PHI"), dict(r)
    assert (r["wins"], r["losses"]) == (4, 2), dict(r)
    assert r["mvp_roman"] == "Jeremy Pena", f"WS MVP={r['mvp_roman']}"


def test_npb_japan_series_with_tie():
    """NPB 일본시리즈는 무승부 포함(2022: ORX가 YS를 4-2-1, MVP 杉本)."""
    _ensure_loaded()
    c = _conn()
    r = _championship(c, "NPB", "JapanSeries", 2022)
    c.close()
    assert r is not None, "NPB 2022 JapanSeries 없음"
    assert (r["win"], r["lose"]) == ("ORX", "YS"), dict(r)
    assert (r["wins"], r["losses"], r["ties"]) == (4, 2, 1), dict(r)
    assert "杉本" in (r["mvp_native"] or ""), f"MVP={r['mvp_native']}"


def test_kbo_korean_series_2024():
    """KBO 2024 한국시리즈: KIA가 SS를 4-1, MVP 김선빈."""
    _ensure_loaded()
    c = _conn()
    r = _championship(c, "KBO", "KoreanSeries", 2024)
    c.close()
    assert r is not None, "KBO 2024 KoreanSeries 없음"
    assert (r["win"], r["lose"]) == ("KIA", "SS"), dict(r)
    assert (r["wins"], r["losses"]) == (4, 1), dict(r)
    assert "김선빈" in (r["mvp_native"] or ""), f"MVP={r['mvp_native']}"


def test_mlb_postseason_rounds():
    """MLB 2022 포스트시즌 전 라운드(WC/DS/CS/WS) 적재 — 다수 시리즈."""
    _ensure_loaded()
    c = _conn()
    n = c.execute(
        "SELECT count(*) FROM postseason_series WHERE league='MLB'"
    ).fetchone()[0]
    c.close()
    assert n >= 10, f"MLB 포스트시즌 시리즈 {n}개 (10+ 기대)"


def test_award_share_winners():
    """award_share 2022 수상자 — MVP/CyYoung/RookieOfYear 각 won=1 존재."""
    _ensure_loaded()
    c = _conn()
    judge = c.execute(
        """SELECT a.won FROM award_share a JOIN person p ON p.id=a.person_id
           WHERE p.name_roman='Aaron Judge' AND a.award='MVP'"""
    ).fetchone()
    awards = {
        r[0]
        for r in c.execute("SELECT DISTINCT award FROM award_share")
    }
    c.close()
    assert judge is not None and judge["won"] == 1, "Aaron Judge MVP(won=1) 없음"
    assert {"MVP", "CyYoung", "RookieOfYear"} <= awards, f"수상 종류 부족: {awards}"


def test_idempotent_reload():
    """postseason.load() 재실행해도 postseason_series/award_share 행 수 불변."""
    _ensure_loaded()
    c = _conn()
    before = (
        c.execute("SELECT count(*) FROM postseason_series").fetchone()[0],
        c.execute("SELECT count(*) FROM award_share").fetchone()[0],
    )
    fk0 = c.execute("PRAGMA foreign_key_check").fetchall()
    c.close()

    postseason.load()  # 재실행

    c = _conn()
    after = (
        c.execute("SELECT count(*) FROM postseason_series").fetchone()[0],
        c.execute("SELECT count(*) FROM award_share").fetchone()[0],
    )
    c.close()
    assert before == after, f"멱등성 위반: {before} -> {after}"
    assert not fk0, f"FK 위반: {fk0}"


if __name__ == "__main__":
    test_championships_present()
    test_mlb_world_series_2022()
    test_npb_japan_series_with_tie()
    test_kbo_korean_series_2024()
    test_mlb_postseason_rounds()
    test_award_share_winners()
    test_idempotent_reload()
    print("all phase6 tests passed")
