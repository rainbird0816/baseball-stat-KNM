"""NPB 수집기 (Phase 4) — npb.jp BIS 공식 통계 크롤링/적재.

robots.txt 가 404(차단 규정 없음)이므로 정중한 크롤만 허용한다:
요청 간 폴리트 딜레이(>=1.5s), User-Agent 명시, 원본 HTML 은
data/raw/npb/<year>/ 에 캐시 후 재파싱(재요청 최소화).

원본 HTML 을 컨텍스트/프롬프트에 통째로 넣지 않는다 — inspect() 는 표
컬럼/행수/샘플 1행 요약만 출력한다.

적재(FK 순서):
  season → franchise → team_season(순위 W-L-T) → person(+external_id) →
  stint → batting_season / pitching_season.  모두 멱등 upsert.

선수명: name_native=일본어. npb.jp BIS 표에는 로마자/안정 선수ID 가 없어
name_roman=NULL, person 식별은 합성키 ('name_native|team_code|year') 의
('npb', synthetic) external_id 로 멱등 보장.

사용:
  python -m backend.ingest.sources.npb_official inspect 2022 bat_c
  python -m backend.ingest.sources.npb_official backfill --year 2022
"""
from __future__ import annotations

import argparse
import io
import math
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw" / "npb"
SOURCE = "npb"
DEFAULT_DB = ROOT / "data" / "baseball.db"

BASE = "https://npb.jp/bis/{year}/stats/{page}.html"
PAGES = ["bat_c", "bat_p", "pit_c", "pit_p", "std_c", "std_p"]
_UA = "baseball-archive ingest (rainbird0816@gmail.com; +npb.jp polite crawl)"
_DELAY = 1.5  # 요청 간 폴리트 딜레이(초)


# --------------------------------------------------------------------------- #
# 캐시/페치
# --------------------------------------------------------------------------- #
def _cache_path(year: int, page: str) -> Path:
    return RAW / str(year) / f"{page}.html"


def fetch(year: int, page: str, force: bool = False) -> str:
    """한 페이지 HTML 을 캐시에서 읽거나(없으면) 다운로드 후 캐시. utf-8 문자열 반환."""
    import requests

    dest = _cache_path(year, page)
    if dest.exists() and dest.stat().st_size > 1000 and not force:
        return dest.read_bytes().decode("utf-8", "replace")
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = BASE.format(year=year, page=page)
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            r = requests.get(url, headers={"User-Agent": _UA}, timeout=30)
            r.raise_for_status()
            dest.write_bytes(r.content)
            time.sleep(_DELAY)  # 크롤 예절
            return r.content.decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(3)
    raise SystemExit(f"네트워크 실패: {url} ({type(last_err).__name__}: {last_err})")


def _tables(html: str):
    import pandas as pd

    return pd.read_html(io.StringIO(html))


def _stat_table(html: str):
    """타격/투구 페이지에서 선수 표만 골라 (헤더 제거된) 데이터행 리스트 반환.

    타격: 표 0 하나. 투구: 표 0/1/2(규정/중간/기타) 각각 27열 → 모두 합침.
    각 표의 row0=캡션 노이즈, row1=헤더 → 제거. (투구는 row0=캡션, row1=헤더)
    선수 표는 컬럼수가 가장 많은(>=18) 표들이고 0열이 순위 숫자다.
    """
    rows: list[list] = []
    for t in _tables(html):
        if t.shape[1] < 18:
            continue
        # 헤더/캡션 행 스킵: 데이터행은 0열이 정수 순위
        for ri in range(t.shape[0]):
            v0 = str(t.iloc[ri, 0]).strip()
            if v0.isdigit():
                rows.append([t.iloc[ri, c] for c in range(t.shape[1])])
    return rows


# --------------------------------------------------------------------------- #
# 값 정규화
# --------------------------------------------------------------------------- #
def _i(v):
    """결측/NaN/빈칸 → None, 그 외 파이썬 int."""
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
    except TypeError:
        pass
    s = str(v).strip().replace(",", "")
    if s in ("", "nan", "-", "－"):
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _name(v):
    """일본어 이름 정규화: 전각/반각 공백 제거(npb 는 姓　名 표기)."""
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "nan"):
        return None
    return s.replace("　", " ").replace("  ", " ").strip()


# --------------------------------------------------------------------------- #
# inspect
# --------------------------------------------------------------------------- #
def inspect(year: int, page: str) -> None:
    """한 페이지 표 구조 요약만 출력 (원본 통째 출력 금지)."""
    import pandas as pd  # noqa: F401

    if page not in PAGES:
        raise SystemExit(f"page 는 {PAGES} 중 하나여야 함 (받음: {page})")
    html = fetch(year, page)
    tabs = _tables(html)
    print(f"[npb {year}/{page}] num_tables={len(tabs)}")
    for i, t in enumerate(tabs):
        note = ""
        if t.shape[1] >= 16:
            # 헤더로 추정되는 행(보통 row1) 표시
            hdr_ri = 1 if t.shape[0] > 1 else 0
            hdr = [str(x)[:6] for x in t.iloc[hdr_ri].tolist()][:28]
            note = f" header~row{hdr_ri}: {hdr}"
        print(f"  table[{i}] shape={t.shape}{note}")
    # 선수/순위 데이터행 수 + 샘플 1행
    if page.startswith(("bat_", "pit_")):
        rows = _stat_table(html)
        print(f"  -> data rows (선수): {len(rows)}")
        if rows:
            print(f"  -> sample[0]: {[str(x) for x in rows[0]]}")
        if page.startswith("pit_") and rows:
            from backend.ingest.normalize.npb_mapping import PIT_COL, ip_to_outs

            r = rows[0]
            w, f = r[PIT_COL["ip_whole"]], r[PIT_COL["ip_frac"]]
            print(f"  -> IP 표기 예: whole={w!r} frac={f!r} -> outs={ip_to_outs(w, f)}")
    else:
        for t in tabs:
            if t.shape[1] >= 16 and t.shape[0] >= 4:
                print(f"  -> 순위표 후보 shape={t.shape}, sample row1:",
                      [str(x) for x in t.iloc[1].tolist()][:6])
                break


# --------------------------------------------------------------------------- #
# backfill
# --------------------------------------------------------------------------- #
def backfill(year: int, db_path: str | None = None) -> None:
    """그 시즌 6개 페이지를 받아 코어 스키마에 멱등 적재."""
    from backend.ingest.load.loader import connect, upsert
    from backend.ingest.normalize import npb_mapping as M

    conn = connect(str(db_path or DEFAULT_DB))
    cur = conn.cursor()

    # ---- 0) 6개 페이지 캐시/로드 ----
    htmls = {p: fetch(year, p) for p in PAGES}

    # ---- 1) season ----
    upsert(conn, "season", [{"league": "NPB", "year": int(year)}],
           conflict_cols=["league", "year"])
    season_id = cur.execute(
        "SELECT id FROM season WHERE league='NPB' AND year=?", (int(year),)
    ).fetchone()["id"]

    # ---- 2) franchise (12개, 멱등 upsert on (league, code)) ----
    fr_rows = [
        {"league": "NPB", "code": code, "lineage": v["lineage"],
         "founded_year": v["founded_year"]}
        for code, v in M.NPB_FRANCHISES.items()
    ]
    upsert(conn, "franchise", fr_rows, conflict_cols=["league", "code"],
           update_cols=["lineage", "founded_year"])
    fr_id_by_code = {
        code: cur.execute(
            "SELECT id FROM franchise WHERE league='NPB' AND code=?", (code,)
        ).fetchone()["id"]
        for code in M.NPB_FRANCHISES
    }

    # ---- 3) team_season (순위표 W-L-T) ----
    ts_id_by_code: dict[str, int] = {}
    for page in ("std_c", "std_p"):
        for t in _tables(htmls[page]):
            if t.shape[1] < 16 or t.shape[0] < 4:
                continue
            # 헤더 row0, 팀행 row1+. 팀 풀네임으로 franchise 매칭.
            for ri in range(1, t.shape[0]):
                full = str(t.iloc[ri, M.STD_COL["name"]])
                code = M.code_for_standings_name(full)
                if code is None:
                    continue
                fr_id = fr_id_by_code[code]
                v = M.NPB_FRANCHISES[code]
                upsert(conn, "team_season", [{
                    "franchise_id": fr_id, "season_id": season_id,
                    "org_id": v["org_id"], "park_id": None,
                    "team_name": v["name_native"], "city": None,
                    "wins": _i(t.iloc[ri, M.STD_COL["w"]]),
                    "losses": _i(t.iloc[ri, M.STD_COL["l"]]),
                    "ties": _i(t.iloc[ri, M.STD_COL["t"]]) or 0,
                    "source": SOURCE,
                }], conflict_cols=["franchise_id", "season_id"])
                ts_id_by_code[code] = cur.execute(
                    "SELECT id FROM team_season WHERE franchise_id=? AND season_id=?",
                    (fr_id, season_id),
                ).fetchone()["id"]
            break  # 순위 표 하나만
    conn.commit()

    # ---- person + stint lookup-or-insert 헬퍼 ----
    def person_stint_for(name_native: str, code: str) -> int | None:
        """합성키로 person 멱등 확보 + stint 확보, stint_id 반환."""
        ts_id = ts_id_by_code.get(code)
        if ts_id is None or not name_native:
            return None
        synth = f"{name_native}|{code}|{year}"
        ext = cur.execute(
            "SELECT person_id FROM person_external_id WHERE source=? AND external_id=?",
            (SOURCE, synth),
        ).fetchone()
        if ext:
            person_id = ext["person_id"]
        else:
            cur.execute(
                "INSERT INTO person (name_native, name_roman) VALUES (?, ?)",
                (name_native, None),  # BIS 표에 로마자 없음 → NULL
            )
            person_id = cur.lastrowid
            upsert(conn, "person_external_id",
                   [{"person_id": person_id, "source": SOURCE, "external_id": synth}],
                   conflict_cols=["source", "external_id"], update_cols=["person_id"])
        # stint (person, team_season, order=1)
        row = cur.execute(
            "SELECT id FROM stint WHERE person_id=? AND team_season_id=? "
            "AND order_in_season=1", (person_id, ts_id),
        ).fetchone()
        if row:
            return row["id"]
        cur.execute(
            "INSERT INTO stint (person_id, team_season_id, order_in_season) "
            "VALUES (?,?,1)", (person_id, ts_id))
        return cur.lastrowid

    # ---- 4) batting_season ----
    bat_n = 0
    for page in ("bat_c", "bat_p"):
        brows = []
        for r in _stat_table(htmls[page]):
            code = M.code_for_abbr(str(r[M.BAT_COL["team"]]))
            if code is None:
                continue
            sid = person_stint_for(_name(r[M.BAT_COL["name"]]), code)
            if sid is None:
                continue
            brows.append({
                "stint_id": sid,
                "g": _i(r[M.BAT_COL["g"]]), "pa": _i(r[M.BAT_COL["pa"]]),
                "ab": _i(r[M.BAT_COL["ab"]]), "r": _i(r[M.BAT_COL["r"]]),
                "h": _i(r[M.BAT_COL["h"]]), "b2": _i(r[M.BAT_COL["b2"]]),
                "b3": _i(r[M.BAT_COL["b3"]]), "hr": _i(r[M.BAT_COL["hr"]]),
                "rbi": _i(r[M.BAT_COL["rbi"]]), "sb": _i(r[M.BAT_COL["sb"]]),
                "cs": _i(r[M.BAT_COL["cs"]]), "bb": _i(r[M.BAT_COL["bb"]]),
                "so": _i(r[M.BAT_COL["so"]]), "ibb": _i(r[M.BAT_COL["ibb"]]),
                "hbp": _i(r[M.BAT_COL["hbp"]]), "sh": _i(r[M.BAT_COL["sh"]]),
                "sf": _i(r[M.BAT_COL["sf"]]), "gidp": _i(r[M.BAT_COL["gidp"]]),
                "extra": None, "source": SOURCE,
            })
        conn.commit()
        brows = list({b["stint_id"]: b for b in brows}.values())
        bat_n += upsert(conn, "batting_season", brows, conflict_cols=["stint_id"])

    # ---- 5) pitching_season ----
    pit_n = 0
    for page in ("pit_c", "pit_p"):
        prows = []
        for r in _stat_table(htmls[page]):
            code = M.code_for_abbr(str(r[M.PIT_COL["team"]]))
            if code is None:
                continue
            sid = person_stint_for(_name(r[M.PIT_COL["name"]]), code)
            if sid is None:
                continue
            outs = M.ip_to_outs(r[M.PIT_COL["ip_whole"]], r[M.PIT_COL["ip_frac"]])
            prows.append({
                "stint_id": sid,
                "w": _i(r[M.PIT_COL["w"]]), "l": _i(r[M.PIT_COL["l"]]),
                "g": _i(r[M.PIT_COL["g"]]), "gs": None,
                "cg": _i(r[M.PIT_COL["cg"]]), "sho": _i(r[M.PIT_COL["sho"]]),
                "sv": _i(r[M.PIT_COL["sv"]]), "hld": _i(r[M.PIT_COL["hld"]]),
                "ip_outs": outs, "h": _i(r[M.PIT_COL["h"]]),
                "r": _i(r[M.PIT_COL["r"]]), "er": _i(r[M.PIT_COL["er"]]),
                "hr": _i(r[M.PIT_COL["hr"]]), "bb": _i(r[M.PIT_COL["bb"]]),
                "so": _i(r[M.PIT_COL["so"]]), "hbp": _i(r[M.PIT_COL["hbp"]]),
                "bk": _i(r[M.PIT_COL["bk"]]), "wp": _i(r[M.PIT_COL["wp"]]),
                "bf": _i(r[M.PIT_COL["bf"]]), "extra": None, "source": SOURCE,
            })
        conn.commit()
        prows = list({p["stint_id"]: p for p in prows}.values())
        pit_n += upsert(conn, "pitching_season", prows, conflict_cols=["stint_id"])

    conn.commit()

    # ---- 요약 ----
    def n(q, *a):
        return cur.execute(q, a).fetchone()[0]

    print(f"backfill year={year} done (source={SOURCE})")
    print("  season_id      :", season_id)
    print("  franchise(NPB) :", n("SELECT count(*) FROM franchise WHERE league='NPB'"))
    print("  team_season    :", n(
        "SELECT count(*) FROM team_season WHERE season_id=?", season_id))
    print("  person(npb ext):", n(
        "SELECT count(DISTINCT person_id) FROM person_external_id WHERE source='npb'"))
    print("  stint(npb ts)  :", n(
        "SELECT count(*) FROM stint s JOIN team_season ts ON s.team_season_id=ts.id "
        "WHERE ts.season_id=?", season_id))
    print("  batting_season :", n(
        "SELECT count(*) FROM batting_season WHERE source='npb'"))
    print("  pitching_season:", n(
        "SELECT count(*) FROM pitching_season WHERE source='npb'"))
    # 순위 샘플 1팀
    samp = cur.execute(
        "SELECT f.code, ts.team_name, ts.wins, ts.losses, ts.ties "
        "FROM team_season ts JOIN franchise f ON ts.franchise_id=f.id "
        "WHERE ts.season_id=? ORDER BY ts.wins DESC LIMIT 1", (season_id,)
    ).fetchone()
    if samp:
        print(f"  순위 샘플      : {samp['code']} {samp['team_name']} "
              f"{samp['wins']}-{samp['losses']}-{samp['ties']}")
    conn.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(prog="npb_official")
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("inspect")
    pi.add_argument("year", type=int)
    pi.add_argument("page", choices=PAGES)
    pb = sub.add_parser("backfill")
    pb.add_argument("--year", type=int, required=True)
    pb.add_argument("--db")
    a = p.parse_args()
    if a.cmd == "inspect":
        inspect(a.year, a.page)
    else:
        backfill(a.year, db_path=a.db)
