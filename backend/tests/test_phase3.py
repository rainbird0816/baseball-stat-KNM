"""Phase 3 — KBO 시즌 스탯(T1) 적재 검증.

KBO 공식 기록실(서버렌더, robots 허용) 적재 결과를 본다. 무승부 ties·이닝 아웃정수·
playerId 인물 식별을 확인한다. init_db --fresh 는 팩트를 비우므로, KBO 2024 시즌이
없으면 캐시된 원본 HTML 로 스스로 적재한 뒤 검증한다(원본은 data/raw/kbo/2024/ 캐시).

실행:
    python -m backend.tests.test_phase3
    pytest backend/tests/test_phase3.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.ingest.sources.kbo_official import backfill

DB = Path(__file__).resolve().parents[2] / "data" / "baseball.db"
SEASON = 2024
GAMES_2024 = 144  # KBO 2024 정규시즌 팀당 경기수


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute("PRAGMA foreign_keys = ON")
    c.row_factory = sqlite3.Row
    c.text_factory = str
    return c


def _kbo_counts(c: sqlite3.Connection) -> dict[str, int]:
    return {
        "team_season": c.execute(
            """SELECT count(*) FROM team_season ts JOIN franchise f ON f.id=ts.franchise_id
               JOIN season se ON se.id=ts.season_id
               WHERE f.league='KBO' AND se.year=?""",
            (SEASON,),
        ).fetchone()[0],
        "batting_season": c.execute(
            """SELECT count(*) FROM batting_season b JOIN stint st ON st.id=b.stint_id
               JOIN team_season ts ON ts.id=st.team_season_id
               JOIN franchise f ON f.id=ts.franchise_id WHERE f.league='KBO'"""
        ).fetchone()[0],
        "pitching_season": c.execute(
            """SELECT count(*) FROM pitching_season p JOIN stint st ON st.id=p.stint_id
               JOIN team_season ts ON ts.id=st.team_season_id
               JOIN franchise f ON f.id=ts.franchise_id WHERE f.league='KBO'"""
        ).fetchone()[0],
        "person_kbo": c.execute(
            "SELECT count(*) FROM person_external_id WHERE source='kbo'"
        ).fetchone()[0],
    }


def _ensure_loaded() -> None:
    c = _conn()
    n = c.execute(
        """SELECT count(*) FROM team_season ts JOIN franchise f ON f.id=ts.franchise_id
           JOIN season se ON se.id=ts.season_id
           WHERE f.league='KBO' AND se.year=?""",
        (SEASON,),
    ).fetchone()[0]
    c.close()
    if n == 0:
        backfill(SEASON)


def test_ten_teams_games_consistent():
    """KBO 10팀, 각 팀 W+L+T == 144(경기 정합)."""
    _ensure_loaded()
    c = _conn()
    rows = c.execute(
        """SELECT f.code, ts.wins, ts.losses, ts.ties
           FROM team_season ts JOIN franchise f ON f.id=ts.franchise_id
           JOIN season se ON se.id=ts.season_id
           WHERE f.league='KBO' AND se.year=?""",
        (SEASON,),
    ).fetchall()
    c.close()
    assert len(rows) == 10, f"team_season {len(rows)} (10 기대)"
    for r in rows:
        s = (r["wins"] or 0) + (r["losses"] or 0) + (r["ties"] or 0)
        assert s == GAMES_2024, f"{r['code']} {r['wins']}-{r['losses']}-{r['ties']} 합={s}"


def test_kia_champion_and_ties_present():
    """KIA 2024 정규시즌 1위 87-55-2, 리그 무승부 합>0(무승부 컬럼 반영)."""
    _ensure_loaded()
    c = _conn()
    kia = c.execute(
        """SELECT ts.wins, ts.losses, ts.ties FROM team_season ts
           JOIN franchise f ON f.id=ts.franchise_id JOIN season se ON se.id=ts.season_id
           WHERE f.league='KBO' AND f.code='KIA' AND se.year=?""",
        (SEASON,),
    ).fetchone()
    tie_sum = c.execute(
        """SELECT COALESCE(SUM(ts.ties),0) FROM team_season ts
           JOIN franchise f ON f.id=ts.franchise_id JOIN season se ON se.id=ts.season_id
           WHERE f.league='KBO' AND se.year=?""",
        (SEASON,),
    ).fetchone()[0]
    c.close()
    assert kia is not None, "KIA 2024 team_season 없음"
    assert (kia["wins"], kia["losses"], kia["ties"]) == (87, 55, 2), dict(kia)
    assert tie_sum > 0, "KBO 무승부 합이 0 (ties 미반영 의심)"


def test_hr_leader_and_known_line():
    """KBO 2024 홈런 1위 = 데이비슨(NC) 46. 김도영(KIA)은 38홈런(40-40 MVP)."""
    _ensure_loaded()
    c = _conn()
    leader = c.execute(
        """SELECT p.name_native, b.hr
           FROM batting_season b JOIN stint st ON st.id=b.stint_id
           JOIN team_season ts ON ts.id=st.team_season_id
           JOIN franchise f ON f.id=ts.franchise_id
           JOIN season se ON se.id=ts.season_id
           JOIN person p ON p.id=st.person_id
           WHERE f.league='KBO' AND se.year=? ORDER BY b.hr DESC LIMIT 1""",
        (SEASON,),
    ).fetchone()
    kim = c.execute(
        """SELECT b.hr, b.r FROM batting_season b JOIN stint st ON st.id=b.stint_id
           JOIN team_season ts ON ts.id=st.team_season_id
           JOIN franchise f ON f.id=ts.franchise_id
           JOIN season se ON se.id=ts.season_id
           JOIN person p ON p.id=st.person_id
           WHERE f.league='KBO' AND se.year=? AND p.name_native LIKE '%김도영%'""",
        (SEASON,),
    ).fetchone()
    c.close()
    assert leader is not None and leader["hr"] == 46, dict(leader) if leader else None
    assert "데이비슨" in (leader["name_native"] or ""), f"HR 1위 {leader['name_native']}"
    assert kim is not None and kim["hr"] == 38, f"김도영 HR={kim['hr'] if kim else None} (38 기대)"


def test_ip_outs_integer():
    """이닝은 아웃 정수 — 음수 없고 환산 소수부 0/1/2."""
    _ensure_loaded()
    c = _conn()
    rows = c.execute(
        """SELECT p.ip_outs FROM pitching_season p JOIN stint st ON st.id=p.stint_id
           JOIN team_season ts ON ts.id=st.team_season_id
           JOIN franchise f ON f.id=ts.franchise_id
           WHERE f.league='KBO' AND p.ip_outs IS NOT NULL"""
    ).fetchall()
    c.close()
    assert rows, "KBO 투구 라인 없음"
    for (outs,) in rows:
        assert outs >= 0 and outs % 3 in (0, 1, 2), f"비정상 ip_outs={outs}"


def test_person_identity_playerid():
    """playerId 식별: source='kbo' external_id 중복 없음, name_native(한글) 채움, source='kbo'."""
    _ensure_loaded()
    c = _conn()
    total = c.execute(
        "SELECT count(*) FROM person_external_id WHERE source='kbo'"
    ).fetchone()[0]
    distinct_ext = c.execute(
        "SELECT count(DISTINCT external_id) FROM person_external_id WHERE source='kbo'"
    ).fetchone()[0]
    null_name = c.execute(
        """SELECT count(*) FROM person p
           JOIN person_external_id x ON x.person_id=p.id AND x.source='kbo'
           WHERE p.name_native IS NULL OR p.name_native=''"""
    ).fetchone()[0]
    bad_src = c.execute(
        """SELECT count(*) FROM batting_season b JOIN stint st ON st.id=b.stint_id
           JOIN team_season ts ON ts.id=st.team_season_id
           JOIN franchise f ON f.id=ts.franchise_id
           WHERE f.league='KBO' AND b.source IS NOT 'kbo'"""
    ).fetchone()[0]
    c.close()
    assert total == distinct_ext, f"kbo external_id 중복: {total} vs distinct {distinct_ext}"
    assert null_name == 0, f"name_native 결측 {null_name}건"
    assert bad_src == 0, f"source!='kbo' {bad_src}건"


def test_idempotent_rebackfill():
    """같은 시즌 재적재해도 KBO 행 수 불변(멱등)."""
    _ensure_loaded()
    c = _conn()
    before = _kbo_counts(c)
    c.close()

    backfill(SEASON)  # 재실행

    c = _conn()
    after = _kbo_counts(c)
    c.close()
    assert before == after, f"멱등성 위반: {before} -> {after}"


if __name__ == "__main__":
    test_ten_teams_games_consistent()
    test_kia_champion_and_ties_present()
    test_hr_leader_and_known_line()
    test_ip_outs_integer()
    test_person_identity_playerid()
    test_idempotent_rebackfill()
    print("all phase3 tests passed")
