"""경기 단위(T2) 조회 — Phase 2 대표 엔드포인트.

날짜별 경기 목록과 한 경기의 박스스코어(타격/투구 라인 + 선수명)를 반환한다.
저장은 ip_outs(아웃 정수)지만 응답에선 표준 이닝 표기(x.0/x.1/x.2)로 환산한다.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import get_conn

router = APIRouter(prefix="/games")


def _ip(outs: int | None) -> str | None:
    return None if outs is None else f"{outs // 3}.{outs % 3}"


@router.get("")
def list_games(date: str, league: str = "MLB"):
    """날짜별 경기 목록. 예: /games?date=2022-04-15"""
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT g.id, g.game_date, g.status, g.innings,
                   ats.team_name AS away, g.away_score,
                   hts.team_name AS home, g.home_score
            FROM game g
            LEFT JOIN team_season hts ON hts.id = g.home_ts_id
            LEFT JOIN team_season ats ON ats.id = g.away_ts_id
            WHERE g.league = ? AND g.game_date = ?
            ORDER BY g.id
            """,
            (league, date),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.get("/{game_id}")
def box_score(game_id: int):
    """한 경기의 박스스코어(메타 + 타격/투구 라인)."""
    conn = get_conn()
    try:
        g = conn.execute(
            """
            SELECT g.id, g.league, g.game_date, g.game_type, g.status, g.innings,
                   g.home_score, g.away_score,
                   hts.team_name AS home_team, ats.team_name AS away_team,
                   pk.name AS park, g.source
            FROM game g
            LEFT JOIN team_season hts ON hts.id = g.home_ts_id
            LEFT JOIN team_season ats ON ats.id = g.away_ts_id
            LEFT JOIN park pk         ON pk.id  = g.park_id
            WHERE g.id = ?
            """,
            (game_id,),
        ).fetchone()
        if g is None:
            raise HTTPException(404, f"game not found: {game_id}")

        batting = [
            dict(r)
            for r in conn.execute(
                """
                SELECT p.name_roman AS player, ts.team_name AS team,
                       b.pa, b.ab, b.r, b.h, b.hr, b.rbi, b.bb, b.so, b.sb
                FROM player_batting_game b
                JOIN person p            ON p.id  = b.person_id
                LEFT JOIN team_season ts ON ts.id = b.team_season_id
                WHERE b.game_id = ?
                ORDER BY ts.id, b.id
                """,
                (game_id,),
            )
        ]

        pitching = []
        for r in conn.execute(
            """
            SELECT p.name_roman AS player, ts.team_name AS team,
                   pg.ip_outs, pg.h, pg.r, pg.er, pg.bb, pg.so, pg.hr,
                   pg.pitches, pg.decision
            FROM player_pitching_game pg
            JOIN person p            ON p.id  = pg.person_id
            LEFT JOIN team_season ts ON ts.id = pg.team_season_id
            WHERE pg.game_id = ?
            ORDER BY ts.id, pg.id
            """,
            (game_id,),
        ):
            d = dict(r)
            d["ip"] = _ip(d.pop("ip_outs"))
            pitching.append(d)

        return {"game": dict(g), "batting": batting, "pitching": pitching}
    finally:
        conn.close()
