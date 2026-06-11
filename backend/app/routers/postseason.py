"""우승 시리즈 & 포스트시즌 조회 — Phase 6 대표 엔드포인트.

월드시리즈·일본시리즈·한국시리즈(리그 최종 우승 결정전)를 크로스리그로 한눈에 보거나,
한 리그·시즌의 전체 포스트시즌 시리즈를 조회한다.
"""
from __future__ import annotations

from fastapi import APIRouter

from ..db import get_conn

router = APIRouter(prefix="/postseason")

_BASE_SQL = """
    SELECT ps.league, ps.round, se.year, ps.is_championship,
           ps.wins, ps.losses, ps.ties,
           fw.code AS winner, tw.team_name AS winner_name,
           fl.code AS loser,  tl.team_name AS loser_name,
           pn.name_native AS mvp_native, pn.name_roman AS mvp_roman,
           ps.source
    FROM postseason_series ps
    JOIN season se ON se.id = ps.season_id
    LEFT JOIN team_season tw ON tw.id = ps.winner_ts_id
    LEFT JOIN franchise   fw ON fw.id = tw.franchise_id
    LEFT JOIN team_season tl ON tl.id = ps.loser_ts_id
    LEFT JOIN franchise   fl ON fl.id = tl.franchise_id
    LEFT JOIN person      pn ON pn.id = ps.mvp_person_id
"""


@router.get("/seasons")
def seasons():
    """포스트시즌 데이터가 있는 (리그, 연도) 목록 — 역대 플레이오프 브라우징 진입점."""
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT ps.league, se.year,
                   COUNT(*) AS series_count,
                   SUM(ps.is_championship) AS has_championship
            FROM postseason_series ps
            JOIN season se ON se.id = ps.season_id
            GROUP BY ps.league, se.year
            ORDER BY se.year DESC, ps.league
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/championships")
def championships():
    """리그 최종 우승 결정전(WS/일본/한국시리즈)만 — 크로스리그 우승 기록."""
    conn = get_conn()
    try:
        rows = conn.execute(
            _BASE_SQL + " WHERE ps.is_championship = 1 ORDER BY se.year DESC, ps.league"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("")
def series(league: str, year: int):
    """한 리그·시즌의 전체 포스트시즌 시리즈. 예: /postseason?league=MLB&year=2022"""
    conn = get_conn()
    try:
        rows = conn.execute(
            _BASE_SQL
            + " WHERE ps.league = ? AND se.year = ?"
            + " ORDER BY ps.is_championship DESC, ps.round",
            (league, year),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
