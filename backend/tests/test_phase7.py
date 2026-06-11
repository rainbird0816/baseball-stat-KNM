"""Phase 7 — 구단 로고 변천사 검증.

team_logo 가 lineage 에서 era 로 적재됐는지, 저작권 규칙(이미지 비저장)을 지키는지 본다.
KBO 프랜차이즈는 seed(005)라 --fresh 후에도 존재하므로 KBO 로고 era 는 항상 생성 가능.
team_logo 가 비어 있으면 logos.load() 로 채운 뒤 검증한다.

실행:
    python -m backend.tests.test_phase7
    pytest backend/tests/test_phase7.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.ingest.sources import logos

DB = Path(__file__).resolve().parents[2] / "data" / "baseball.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute("PRAGMA foreign_keys = ON")
    c.row_factory = sqlite3.Row
    c.text_factory = str
    return c


def _ensure_loaded() -> None:
    c = _conn()
    n = c.execute("SELECT count(*) FROM team_logo").fetchone()[0]
    c.close()
    if n == 0:
        logos.load()


def _eras(c, code, league="KBO"):
    return c.execute(
        """SELECT tl.valid_from_year AS f, tl.valid_to_year AS t, tl.note
           FROM team_logo tl JOIN franchise fr ON fr.id=tl.franchise_id
           WHERE fr.code=? AND fr.league=? AND tl.logo_type='primary'
           ORDER BY tl.valid_from_year""",
        (code, league),
    ).fetchall()


def test_kbo_wo_three_eras():
    """키움(WO) 3개 era: 우리(2008-2009)→넥센(2010-2018)→키움(2019-현재)."""
    _ensure_loaded()
    c = _conn()
    eras = _eras(c, "WO")
    c.close()
    bounds = [(e["f"], e["t"]) for e in eras]
    assert bounds == [(2008, 2009), (2010, 2018), (2019, None)], bounds
    assert "키움" in (eras[-1]["note"] or ""), eras[-1]["note"]


def test_kbo_kia_two_eras():
    """KIA 2개 era: 해태(1982-2000)→KIA(2001-현재)."""
    _ensure_loaded()
    c = _conn()
    eras = _eras(c, "KIA")
    c.close()
    bounds = [(e["f"], e["t"]) for e in eras]
    assert bounds == [(1982, 2000), (2001, None)], bounds


def test_disbanded_franchise_closed():
    """해체 구단(HD 현대)도 era 가 남고 마지막 era 가 닫혀 있다(valid_to_year 존재)."""
    _ensure_loaded()
    c = _conn()
    eras = _eras(c, "HD")
    c.close()
    assert len(eras) >= 3, f"HD era {len(eras)}개"
    assert eras[-1]["t"] is not None, "해체 구단 마지막 era 가 안 닫힘"


def test_copyright_no_images():
    """저작권 규칙: image_path 는 전부 NULL, source_url 은 채워져 있다."""
    _ensure_loaded()
    c = _conn()
    with_img = c.execute(
        "SELECT count(*) FROM team_logo WHERE image_path IS NOT NULL"
    ).fetchone()[0]
    no_src = c.execute(
        "SELECT count(*) FROM team_logo WHERE source_url IS NULL OR source_url=''"
    ).fetchone()[0]
    c.close()
    assert with_img == 0, f"image_path 채워진 행 {with_img} (저작권 규칙 위반)"
    assert no_src == 0, f"source_url 결측 {no_src}건"


def test_kbo_multi_era():
    """KBO 는 multi-era 라 로고 행 수 > 프랜차이즈 수."""
    _ensure_loaded()
    c = _conn()
    n_logo = c.execute(
        """SELECT count(*) FROM team_logo tl JOIN franchise fr ON fr.id=tl.franchise_id
           WHERE fr.league='KBO'"""
    ).fetchone()[0]
    n_fr = c.execute("SELECT count(*) FROM franchise WHERE league='KBO'").fetchone()[0]
    c.close()
    assert n_logo > n_fr, f"KBO logo {n_logo} <= franchise {n_fr} (multi-era 기대)"


def test_idempotent_reload():
    """logos.load() 재실행해도 team_logo 행 수 불변(멱등), FK 무결."""
    _ensure_loaded()
    c = _conn()
    before = c.execute("SELECT count(*) FROM team_logo").fetchone()[0]
    c.close()

    logos.load()  # 재실행

    c = _conn()
    after = c.execute("SELECT count(*) FROM team_logo").fetchone()[0]
    fk = c.execute("PRAGMA foreign_key_check").fetchall()
    c.close()
    assert before == after, f"멱등성 위반: {before} -> {after}"
    assert not fk, f"FK 위반: {fk}"


if __name__ == "__main__":
    test_kbo_wo_three_eras()
    test_kbo_kia_two_eras()
    test_disbanded_franchise_closed()
    test_copyright_no_images()
    test_kbo_multi_era()
    test_idempotent_reload()
    print("all phase7 tests passed")
