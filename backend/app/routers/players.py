"""선수 커리어 조회 — Phase 1 대표 엔드포인트.

크로스리그 통합 커리어 뷰의 진입점. person_external_id 로 소스 ID(예 Lahman
playerID)를 받아 person 을 찾고, stint→team_season→season 을 따라 시즌별
타격/투구 스탯을 반환한다. (리그가 늘어나도 같은 person 한 행이면 그대로 합쳐진다.)
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import get_conn

router = APIRouter(prefix="/players")


@router.get("/multi-league")
def multi_league():
    """둘 이상 리그에서 뛴 통합 인물(크로스리그 이동 선수) 목록 — Phase 5 결과.

    person 한 행의 stint 가 2개 이상 리그에 걸친 경우만 추린다. 각 인물에 커리어
    조회용 대표 external_id(ref_source/ref_id)를 함께 준다(mlbam>lahman>kbo>npb 우선).
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.name_native, p.name_roman,
                   GROUP_CONCAT(DISTINCT se.league) AS leagues,
                   COUNT(DISTINCT se.league) AS n_leagues,
                   (SELECT x.source || ':' || x.external_id
                    FROM person_external_id x WHERE x.person_id = p.id
                    ORDER BY CASE x.source
                        WHEN 'mlbam' THEN 1 WHEN 'lahman' THEN 2
                        WHEN 'kbo' THEN 3 WHEN 'npb' THEN 4 ELSE 5 END
                    LIMIT 1) AS ref
            FROM person p
            JOIN stint st       ON st.person_id = p.id
            JOIN team_season ts ON ts.id = st.team_season_id
            JOIN season se      ON se.id = ts.season_id
            GROUP BY p.id
            HAVING n_leagues > 1
            ORDER BY p.name_roman
            """
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            ref = d.pop("ref") or ""
            d["ref_source"], _, d["ref_id"] = ref.partition(":")
            out.append(d)
        return out
    finally:
        conn.close()


@router.get("/{source}/{external_id}/career")
def career(source: str, external_id: str):
    """소스 ID(예: source='lahman', external_id='judgeaa01')로 커리어 조회."""
    conn = get_conn()
    try:
        person = conn.execute(
            "SELECT p.id, p.name_native, p.name_roman, p.birth_date, p.bats, p.throws "
            "FROM person p JOIN person_external_id x ON x.person_id = p.id "
            "WHERE x.source = ? AND x.external_id = ?",
            (source, external_id),
        ).fetchone()
        if person is None:
            raise HTTPException(404, f"person not found: {source}:{external_id}")

        rows = conn.execute(
            """
            SELECT se.year, se.league, ts.team_name, st.order_in_season AS stint,
                   b.g AS bat_g, b.pa, b.ab, b.h, b.b2, b.b3, b.hr, b.rbi,
                   b.sb, b.bb, b.so,
                   p.g AS pit_g, p.w, p.l, p.sv, p.ip_outs,
                   p.h AS p_h, p.er, p.so AS p_so, p.bb AS p_bb
            FROM stint st
            JOIN team_season ts ON ts.id = st.team_season_id
            JOIN season se      ON se.id = ts.season_id
            LEFT JOIN batting_season  b ON b.stint_id = st.id
            LEFT JOIN pitching_season p ON p.stint_id = st.id
            WHERE st.person_id = ?
            ORDER BY se.year, st.order_in_season
            """,
            (person["id"],),
        ).fetchall()

        seasons = []
        for r in rows:
            d = dict(r)
            # 이닝은 저장은 아웃 정수, 표현할 때만 환산
            outs = d.pop("ip_outs")
            d["ip"] = None if outs is None else f"{outs // 3}.{outs % 3}"
            # 타격/투구 라인이 비어있으면(전부 NULL) 생략해 응답을 가볍게
            d["batting"] = d["bat_g"] is not None
            d["pitching"] = d["pit_g"] is not None
            seasons.append(d)

        return {
            "person": dict(person),
            "external": {"source": source, "external_id": external_id},
            "seasons": seasons,
        }
    finally:
        conn.close()
