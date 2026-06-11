from fastapi import APIRouter
from ..db import get_conn

router = APIRouter(prefix="/leagues")


@router.get("")
def list_leagues():
    """org 레벨 리그 목록 + 규칙 요약 (리그별 페이지의 진입점)."""
    conn = get_conn()
    orgs = [
        dict(r)
        for r in conn.execute(
            "SELECT short_code, name FROM organization WHERE level='org' ORDER BY id"
        )
    ]
    for o in orgs:
        o["rules"] = [
            dict(r)
            for r in conn.execute(
                "SELECT rule_key, rule_value, valid_from_year, valid_to_year "
                "FROM league_rule WHERE league=? ORDER BY rule_key",
                (o["short_code"],),
            )
        ]
    conn.close()
    return orgs


@router.get("/{code}/franchises")
def franchises(code: str):
    conn = get_conn()
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT code, lineage, founded_year FROM franchise "
            "WHERE league=? ORDER BY founded_year",
            (code,),
        )
    ]
    conn.close()
    return rows


@router.get("/{code}/standings")
def standings(code: str, year: int):
    """시즌 순위표(W-L-T). NPB/KBO 무승부와 CL/PL 등 서브리그 계층을 함께 보여준다.

    예: /leagues/NPB/standings?year=2022
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT ts.team_name, o.short_code AS subleague, o.name AS subleague_name,
                   ts.wins, ts.losses, ts.ties
            FROM team_season ts
            JOIN franchise f ON f.id = ts.franchise_id
            JOIN season se   ON se.id = ts.season_id
            LEFT JOIN organization o ON o.id = ts.org_id
            WHERE f.league = ? AND se.year = ?
            ORDER BY o.short_code, CAST(ts.wins AS REAL) /
                     NULLIF(ts.wins + ts.losses, 0) DESC
            """,
            (code, year),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            w, l = d["wins"] or 0, d["losses"] or 0
            d["win_pct"] = round(w / (w + l), 3) if (w + l) else None  # 무승부 제외(KBO/NPB 관례)
            out.append(d)
        return out
    finally:
        conn.close()
