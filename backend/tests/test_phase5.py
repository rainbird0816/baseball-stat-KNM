"""Phase 5 — 크로스리그 인물 매칭 검증.

NPB↔MLB 이동 선수(데모: 스즈키 세이야 鈴木誠也, NPB 広島 2021 → MLB Cubs 2022)가
하나의 person 으로 통합되어 커리어가 두 리그에 걸쳐 조회되는지 본다.

init_db --fresh 는 팩트를 비우므로, 비어 있으면 캐시된 원본으로 MLB 2022 + NPB 2021 을
적재하고 person_match.run() 으로 병합한 뒤 검증한다.

실행:
    python -m backend.tests.test_phase5
    pytest backend/tests/test_phase5.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.ingest.load.loader import connect
from backend.ingest.normalize.person_match import run as match_run
from backend.ingest.sources.mlb_lahman import load as load_season
from backend.ingest.sources.npb_official import backfill as npb_backfill

DB = Path(__file__).resolve().parents[2] / "data" / "baseball.db"
SUZUKI_MLBAM = "673548"      # Seiya Suzuki
SUZUKI_KANJI = "鈴木誠也"     # 원어(공백 제거형)


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute("PRAGMA foreign_keys = ON")
    c.row_factory = sqlite3.Row
    c.text_factory = str
    return c


def _person_id(c: sqlite3.Connection, source: str, ext: str) -> int | None:
    r = c.execute(
        "SELECT person_id FROM person_external_id WHERE source=? AND external_id=?",
        (source, ext),
    ).fetchone()
    return r[0] if r else None


def _ensure_loaded() -> None:
    c = _conn()
    has_mlb = _person_id(c, "mlbam", SUZUKI_MLBAM) is not None
    has_npb_2021 = c.execute(
        "SELECT 1 FROM season WHERE league='NPB' AND year=2021"
    ).fetchone() is not None
    # 이미 병합됐는지: mlbam-스즈키 person 이 npb external_id 도 갖는가
    merged = False
    pid = _person_id(c, "mlbam", SUZUKI_MLBAM)
    if pid is not None:
        merged = c.execute(
            "SELECT 1 FROM person_external_id WHERE person_id=? AND source='npb'",
            (pid,),
        ).fetchone() is not None
    c.close()

    if not has_mlb:
        load_season(2022)
    if not has_npb_2021:
        npb_backfill(2021)
    if not merged:
        conn = connect(str(DB))
        match_run(conn)
        conn.close()


def test_unified_person_spans_two_leagues():
    """통합 person 의 stint 가 NPB·MLB 두 리그에 걸친다."""
    _ensure_loaded()
    c = _conn()
    pid = _person_id(c, "mlbam", SUZUKI_MLBAM)
    assert pid is not None, "MLB 스즈키 person 없음"
    leagues = {
        r[0]
        for r in c.execute(
            """SELECT DISTINCT se.league
               FROM stint st JOIN team_season ts ON ts.id=st.team_season_id
               JOIN season se ON se.id=ts.season_id
               WHERE st.person_id=?""",
            (pid,),
        )
    }
    c.close()
    assert {"NPB", "MLB"} <= leagues, f"두 리그 stint 기대, 실제={leagues}"


def test_external_ids_unified():
    """병합으로 mlbam + npb external_id 가 한 person 에 묶인다."""
    _ensure_loaded()
    c = _conn()
    pid = _person_id(c, "mlbam", SUZUKI_MLBAM)
    srcs = {
        r[0]
        for r in c.execute(
            "SELECT source FROM person_external_id WHERE person_id=?", (pid,)
        )
    }
    c.close()
    assert {"mlbam", "npb", "lahman"} <= srcs, f"external_id 통합 미흡: {srcs}"


def test_native_and_roman_name():
    """원어(한자) name_native + 로마자 name_roman 병기."""
    _ensure_loaded()
    c = _conn()
    pid = _person_id(c, "mlbam", SUZUKI_MLBAM)
    row = c.execute(
        "SELECT name_native, name_roman FROM person WHERE id=?", (pid,)
    ).fetchone()
    c.close()
    assert row["name_native"] == SUZUKI_KANJI, f"name_native={row['name_native']!r}"
    assert row["name_roman"] == "Seiya Suzuki", f"name_roman={row['name_roman']!r}"


def test_cross_league_career_lines():
    """통합 커리어에 NPB 2021 + MLB 2022 타격 라인이 모두 있다."""
    _ensure_loaded()
    c = _conn()
    pid = _person_id(c, "mlbam", SUZUKI_MLBAM)
    rows = c.execute(
        """SELECT se.year, se.league, b.h, b.hr
           FROM stint st JOIN team_season ts ON ts.id=st.team_season_id
           JOIN season se ON se.id=ts.season_id
           JOIN batting_season b ON b.stint_id=st.id
           WHERE st.person_id=? ORDER BY se.year""",
        (pid,),
    ).fetchall()
    c.close()
    seasons = {(r["year"], r["league"]) for r in rows}
    assert (2021, "NPB") in seasons, f"NPB 2021 라인 없음: {seasons}"
    assert (2022, "MLB") in seasons, f"MLB 2022 라인 없음: {seasons}"


def test_idempotent_match_and_fk_clean():
    """매칭 재실행 시 병합 0건, person count 불변, FK 무결."""
    _ensure_loaded()
    c = _conn()
    before = c.execute("SELECT count(*) FROM person").fetchone()[0]
    c.close()

    conn = connect(str(DB))
    merged = match_run(conn)
    conn.close()

    c = _conn()
    after = c.execute("SELECT count(*) FROM person").fetchone()[0]
    fk = c.execute("PRAGMA foreign_key_check").fetchall()
    c.close()
    assert merged == 0, f"재실행 병합 {merged}건 (0 기대 — 멱등성 위반)"
    assert before == after, f"person count {before} -> {after}"
    assert not fk, f"FK 위반: {fk}"


if __name__ == "__main__":
    test_unified_person_spans_two_leagues()
    test_external_ids_unified()
    test_native_and_roman_name()
    test_cross_league_career_lines()
    test_idempotent_match_and_fk_clean()
    print("all phase5 tests passed")
