"""프랜차이즈 히스토리 타임라인 — Phase 7 대표 엔드포인트.

한 프랜차이즈의 정체성 변천(이름 계보 + 로고 era)과 시즌별 팀명/성적을 한 줄기로
보여준다. 로고 이미지는 저작권 보호 대상이라 메타데이터(연도/이름/출처링크)만 담는다.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import get_conn

router = APIRouter(prefix="/franchises")


@router.get("/{code}/history")
def history(code: str, league: str | None = None):
    """프랜차이즈 히스토리(계보 + 로고 era + 시즌별 팀명).

    code 가 리그 간 겹칠 수 있어 모호하면 league 로 좁힌다.
    예: /franchises/WO/history?league=KBO
    """
    conn = get_conn()
    try:
        if league:
            frows = conn.execute(
                "SELECT id, league, code, lineage, founded_year FROM franchise "
                "WHERE code=? AND league=?",
                (code, league),
            ).fetchall()
        else:
            frows = conn.execute(
                "SELECT id, league, code, lineage, founded_year FROM franchise "
                "WHERE code=?",
                (code,),
            ).fetchall()
        if not frows:
            raise HTTPException(404, f"franchise not found: {code}")
        if len(frows) > 1:
            raise HTTPException(
                400,
                f"code '{code}' 가 여러 리그에 존재합니다. league 쿼리로 좁히세요: "
                + ", ".join(r["league"] for r in frows),
            )
        fr = frows[0]

        logos = [
            dict(r)
            for r in conn.execute(
                "SELECT logo_type, valid_from_year, valid_to_year, note, "
                "source_url, image_path FROM team_logo "
                "WHERE franchise_id=? ORDER BY valid_from_year IS NULL, valid_from_year",
                (fr["id"],),
            )
        ]
        seasons = [
            dict(r)
            for r in conn.execute(
                "SELECT se.year, ts.team_name, ts.wins, ts.losses, ts.ties "
                "FROM team_season ts JOIN season se ON se.id=ts.season_id "
                "WHERE ts.franchise_id=? ORDER BY se.year",
                (fr["id"],),
            )
        ]
        return {
            "franchise": {
                "code": fr["code"],
                "league": fr["league"],
                "lineage": fr["lineage"],
                "founded_year": fr["founded_year"],
            },
            "logo_eras": logos,
            "seasons": seasons,
        }
    finally:
        conn.close()
