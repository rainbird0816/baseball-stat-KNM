"""적재 커버리지/신선도 — Phase 8(당일 증분) 모니터링 엔드포인트.

리그별로 어떤 시즌·경기가 적재됐는지, 가장 최근 경기 날짜는 언제인지 요약한다.
daily 증분이 무엇을 확장하는지 확인하는 용도(스케줄러 헬스체크).
"""
from __future__ import annotations

from fastapi import APIRouter

from ..db import get_conn

router = APIRouter(prefix="/status")


@router.get("")
def status():
    conn = get_conn()
    try:
        leagues = [
            r[0] for r in conn.execute("SELECT DISTINCT league FROM season ORDER BY league")
        ]
        out = {}
        for lg in leagues:
            seasons = [
                r[0]
                for r in conn.execute(
                    "SELECT year FROM season WHERE league=? ORDER BY year", (lg,)
                )
            ]
            team_seasons = conn.execute(
                "SELECT count(*) FROM team_season ts JOIN franchise f ON f.id=ts.franchise_id "
                "WHERE f.league=?",
                (lg,),
            ).fetchone()[0]
            g = conn.execute(
                "SELECT count(*), min(game_date), max(game_date) FROM game WHERE league=?",
                (lg,),
            ).fetchone()
            out[lg] = {
                "seasons": seasons,
                "team_seasons": team_seasons,
                "games": {
                    "count": g[0],
                    "first_date": g[1],
                    "last_date": g[2],  # daily 증분이 이어붙일 기준점
                },
            }
        return {"leagues": out}
    finally:
        conn.close()
