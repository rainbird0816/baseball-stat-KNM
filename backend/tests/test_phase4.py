"""Phase 4 — NPB 시즌 스탯(T1) 적재 검증.

NPB 무승부(ties)·센트럴/퍼시픽 계층·이닝 아웃정수 환산을 본다.
init_db --fresh 는 팩트를 비우므로, NPB franchise 가 없으면 캐시된 원본 HTML 로
2022 시즌을 스스로 적재한 뒤 검증한다(원본은 data/raw/npb/2022/ 에 캐시되어 있어야 함).

실행:
    python -m backend.tests.test_phase4
    pytest backend/tests/test_phase4.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.ingest.sources.npb_official import backfill

DB = Path(__file__).resolve().parents[2] / "data" / "baseball.db"
SEASON = 2022
GAMES_2022 = 143  # NPB 2022 정규시즌 팀당 경기수

FACT_TABLES = (
    "franchise", "team_season", "person", "stint",
    "batting_season", "pitching_season",
)


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute("PRAGMA foreign_keys = ON")
    c.row_factory = sqlite3.Row
    c.text_factory = str
    return c


def _npb_counts(c: sqlite3.Connection) -> dict[str, int]:
    return {
        "franchise": c.execute(
            "SELECT count(*) FROM franchise WHERE league='NPB'"
        ).fetchone()[0],
        "team_season": c.execute(
            """SELECT count(*) FROM team_season ts JOIN franchise f ON f.id=ts.franchise_id
               WHERE f.league='NPB'"""
        ).fetchone()[0],
        "batting_season": c.execute(
            """SELECT count(*) FROM batting_season b JOIN stint st ON st.id=b.stint_id
               JOIN team_season ts ON ts.id=st.team_season_id
               JOIN franchise f ON f.id=ts.franchise_id WHERE f.league='NPB'"""
        ).fetchone()[0],
        "pitching_season": c.execute(
            """SELECT count(*) FROM pitching_season p JOIN stint st ON st.id=p.stint_id
               JOIN team_season ts ON ts.id=st.team_season_id
               JOIN franchise f ON f.id=ts.franchise_id WHERE f.league='NPB'"""
        ).fetchone()[0],
    }


def _ensure_loaded() -> None:
    c = _conn()
    n = c.execute("SELECT count(*) FROM franchise WHERE league='NPB'").fetchone()[0]
    c.close()
    if n == 0:
        backfill(SEASON)


def test_twelve_franchises_split_6_6():
    """NPB 12 프랜차이즈, 센트럴/퍼시픽 6:6."""
    _ensure_loaded()
    c = _conn()
    n = c.execute("SELECT count(*) FROM franchise WHERE league='NPB'").fetchone()[0]
    split = dict(
        c.execute(
            """SELECT o.short_code, count(*)
               FROM team_season ts JOIN season se ON se.id=ts.season_id
               JOIN organization o ON o.id=ts.org_id
               WHERE se.year=? GROUP BY o.short_code""",
            (SEASON,),
        ).fetchall()
    )
    c.close()
    assert n == 12, f"NPB franchise {n} (12 기대)"
    assert split.get("CL") == 6 and split.get("PL") == 6, f"CL/PL 분할 {split}"


def test_standings_games_and_ties():
    """각 팀 W+L+T == 143, 모든 팀 무승부 ties>=1(NPB)."""
    _ensure_loaded()
    c = _conn()
    rows = c.execute(
        """SELECT ts.team_name, ts.wins, ts.losses, ts.ties
           FROM team_season ts JOIN franchise f ON f.id=ts.franchise_id
           JOIN season se ON se.id=ts.season_id
           WHERE f.league='NPB' AND se.year=?""",
        (SEASON,),
    ).fetchall()
    c.close()
    assert len(rows) == 12, f"team_season {len(rows)} (12 기대)"
    for r in rows:
        w, l, t = r["wins"], r["losses"], r["ties"]
        assert (w + l + t) == GAMES_2022, f"{r['team_name']} {w}-{l}-{t} 합 != {GAMES_2022}"
        assert t is not None and t >= 1, f"{r['team_name']} ties={t} (NPB 무승부 기대)"


def test_ip_outs_integer():
    """이닝은 아웃 정수 — 음수 없고 환산 소수부 0/1/2, 합리적 최댓값."""
    _ensure_loaded()
    c = _conn()
    rows = c.execute(
        """SELECT p.ip_outs FROM pitching_season p JOIN stint st ON st.id=p.stint_id
           JOIN team_season ts ON ts.id=st.team_season_id
           JOIN franchise f ON f.id=ts.franchise_id
           WHERE f.league='NPB' AND p.ip_outs IS NOT NULL""",
    ).fetchall()
    c.close()
    assert rows, "NPB 투구 라인 없음"
    for (outs,) in rows:
        assert outs >= 0 and outs % 3 in (0, 1, 2), f"비정상 ip_outs={outs}"
    # 한 시즌 ip_outs sanity 상한 — 워크호스 시즌(예 Darvish 2011 232이닝=696 outs)을
    # 허용하되, 파싱 오류(예 수천)는 걸러낸다. 1000 ≈ 333이닝(NPB 역대 기록 마진 위).
    assert max(o for (o,) in rows) <= 1000, f"비현실적 ip_outs max={max(o for (o,) in rows)}"


def test_provenance_native_name():
    """source='npb' provenance + name_native(일본어) 채움."""
    _ensure_loaded()
    c = _conn()
    bad_src = c.execute(
        """SELECT count(*) FROM batting_season b JOIN stint st ON st.id=b.stint_id
           JOIN team_season ts ON ts.id=st.team_season_id
           JOIN franchise f ON f.id=ts.franchise_id
           WHERE f.league='NPB' AND b.source IS NOT 'npb'"""
    ).fetchone()[0]
    null_name = c.execute(
        """SELECT count(*) FROM person p
           JOIN person_external_id x ON x.person_id=p.id AND x.source='npb'
           WHERE p.name_native IS NULL OR p.name_native=''"""
    ).fetchone()[0]
    c.close()
    assert bad_src == 0, f"source!='npb' {bad_src}건"
    assert null_name == 0, f"name_native 결측 {null_name}건"


def test_idempotent_rebackfill():
    """같은 시즌 재적재해도 NPB 행 수 불변(멱등)."""
    _ensure_loaded()
    c = _conn()
    before = _npb_counts(c)
    c.close()

    backfill(SEASON)  # 재실행

    c = _conn()
    after = _npb_counts(c)
    c.close()
    assert before == after, f"멱등성 위반: {before} -> {after}"


if __name__ == "__main__":
    test_twelve_franchises_split_6_6()
    test_standings_games_and_ties()
    test_ip_outs_integer()
    test_provenance_native_name()
    test_idempotent_rebackfill()
    print("all phase4 tests passed")
