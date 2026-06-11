"""Phase 1 — MLB 시즌 스탯(T1) 적재 검증.

스키마만 보는 test_schema 와 달리 '데이터가 올바르게 적재됐는가'를 본다.
init_db --fresh 는 팩트를 비우므로, 비어 있으면 캐시된 Lahman CSV 로 2022 시즌을
스스로 적재한 뒤 검증한다(원본은 data/raw/lahman/ 에 캐시되어 있어야 함).

실행:
    python -m backend.tests.test_phase1
    pytest backend/tests/test_phase1.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.ingest.sources.mlb_lahman import load

DB = Path(__file__).resolve().parents[2] / "data" / "baseball.db"
SEASON = 2022  # 공개 Lahman 미러의 최신 시즌(2023.1 릴리스 = 2022까지)

# 팩트 적재가 멱등인지 비교할 테이블들
FACT_TABLES = (
    "season", "park", "franchise", "team_season",
    "person", "person_external_id", "stint",
    "batting_season", "pitching_season", "fielding_season",
)


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute("PRAGMA foreign_keys = ON")
    c.row_factory = sqlite3.Row
    return c


def _counts(c: sqlite3.Connection) -> dict[str, int]:
    return {t: c.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in FACT_TABLES}


def _ensure_loaded() -> None:
    c = _conn()
    n = c.execute("SELECT count(*) FROM batting_season").fetchone()[0]
    c.close()
    if n == 0:
        load(SEASON)


def test_hr_leader_2022():
    """MLB 2022 홈런 1위 = Aaron Judge 62개(AL 신기록). 공개 총계와 대조."""
    _ensure_loaded()
    c = _conn()
    row = c.execute(
        """
        SELECT p.name_roman, b.hr
        FROM batting_season b
        JOIN stint st       ON st.id = b.stint_id
        JOIN team_season ts ON ts.id = st.team_season_id
        JOIN season se      ON se.id = ts.season_id
        JOIN person p       ON p.id  = st.person_id
        WHERE se.year = ? AND se.league = 'MLB'
        ORDER BY b.hr DESC LIMIT 1
        """,
        (SEASON,),
    ).fetchone()
    c.close()
    assert row is not None, "2022 타격 데이터 없음"
    assert row["hr"] == 62, f"HR 1위 {row['hr']} (62 기대)"
    assert "Judge" in (row["name_roman"] or ""), f"HR 1위 {row['name_roman']} (Judge 기대)"


def test_pa_derivation():
    """파생 규칙 pa = AB+BB+HBP+SF+SH 가 저장값과 일치(전 행)."""
    _ensure_loaded()
    c = _conn()
    rows = c.execute(
        """
        SELECT b.pa, b.ab, b.bb, b.hbp, b.sf, b.sh
        FROM batting_season b
        JOIN stint st       ON st.id = b.stint_id
        JOIN team_season ts ON ts.id = st.team_season_id
        JOIN franchise f    ON f.id = ts.franchise_id
        JOIN season se      ON se.id = ts.season_id
        WHERE f.league = 'MLB' AND se.year = ?
        """,
        (SEASON,),
    ).fetchall()
    c.close()
    assert rows, "타격 행 없음"
    # pa = AB+BB+HBP+SF+SH 는 Lahman/MLB 파생 규칙(NPB/KBO 는 원본 pa 라 제외).
    for r in rows:
        comp = sum((r[k] or 0) for k in ("ab", "bb", "hbp", "sf", "sh"))
        assert r["pa"] == comp, f"pa={r['pa']} != AB+BB+HBP+SF+SH={comp}"


def test_multistint_trade_player():
    """트레이드 선수는 시즌 내 stint 2개 이상으로 분리 저장된다."""
    _ensure_loaded()
    c = _conn()
    row = c.execute(
        """
        SELECT st.person_id, count(*) AS n
        FROM stint st
        JOIN team_season ts ON ts.id = st.team_season_id
        JOIN season se      ON se.id = ts.season_id
        WHERE se.year = ?
        GROUP BY st.person_id ORDER BY n DESC LIMIT 1
        """,
        (SEASON,),
    ).fetchone()
    c.close()
    assert row and row["n"] >= 2, "멀티 스틴트(트레이드) 선수 없음 — stint 분리 실패 의심"


def test_ip_outs_integer():
    """이닝은 아웃 정수로 저장 — 음수/소수 없이 정수이며 표기 환산이 표준 범위."""
    _ensure_loaded()
    c = _conn()
    bad = c.execute(
        "SELECT count(*) FROM pitching_season WHERE ip_outs IS NOT NULL AND ip_outs < 0"
    ).fetchone()[0]
    # 환산 시 소수부는 0/1/2 만 나와야 표준 이닝 표기(x.0/x.1/x.2)와 맞는다
    sample = c.execute(
        "SELECT ip_outs FROM pitching_season WHERE ip_outs IS NOT NULL LIMIT 50"
    ).fetchall()
    c.close()
    assert bad == 0, f"음수 ip_outs {bad}건"
    for (outs,) in sample:
        assert outs % 3 in (0, 1, 2)


def test_provenance_and_ties():
    """source='lahman' provenance 와 ties 기본값(0) 규칙."""
    _ensure_loaded()
    c = _conn()
    bad_src = c.execute(
        """SELECT count(*) FROM batting_season b
           JOIN stint st ON st.id = b.stint_id
           JOIN team_season ts ON ts.id = st.team_season_id
           JOIN franchise f ON f.id = ts.franchise_id
           WHERE f.league = 'MLB' AND b.source IS NOT 'lahman'"""
    ).fetchone()[0]
    null_ties = c.execute(
        "SELECT count(*) FROM team_season WHERE ties IS NULL"
    ).fetchone()[0]
    c.close()
    assert bad_src == 0, f"MLB batting source!='lahman' {bad_src}건"
    assert null_ties == 0, f"ties NULL {null_ties}건 (항상 채워야 함)"


def test_idempotent_reload():
    """같은 시즌을 재적재해도 모든 팩트 테이블 행 수가 불변(멱등)."""
    _ensure_loaded()
    c = _conn()
    before = _counts(c)
    c.close()

    load(SEASON)  # 재실행

    c = _conn()
    after = _counts(c)
    c.close()
    assert before == after, f"멱등성 위반: {before} -> {after}"


if __name__ == "__main__":
    test_hr_leader_2022()
    test_pa_derivation()
    test_multistint_trade_player()
    test_ip_outs_integer()
    test_provenance_and_ties()
    test_idempotent_reload()
    print("all phase1 tests passed")
