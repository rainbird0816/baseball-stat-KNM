"""구단 로고 변천 수집기 (Phase 7).

team_logo 에 프랜차이즈별 식별 era(로고 변천) 메타데이터를 적재한다.

저작권 핵심 규칙
  - **로고 이미지는 다운로드/저장하지 않는다.** 상표·저작권 보호 대상이므로
    image_path 는 전부 NULL. 저장하는 것은 출처 링크(source_url)와 메타데이터
    (연도 경계 / 팀명 / note) 뿐이다. 라이선스 확인된 에셋만 data/assets/logos/
    에 두는데 현재는 없음 → image_path NULL.
  - 멱등 upsert (loader.upsert). conflict=(franchise_id, logo_type, valid_from_year).
    재실행해도 행이 늘지 않는다.
  - 네트워크 요청 없음. source_url 은 출처 포인터(문서 링크) 문자열만 메타로 저장.

리그별 전략
  A) KBO — franchise.lineage 가 연도를 포함한다("이름(연도)→이름(연도)→…").
     이를 파싱해 각 팀명 era 를 team_logo 행으로 만든다.
       logo_type='primary', valid_from_year=era 시작연도,
       valid_to_year=다음 era 시작연도-1 (마지막 era 는 NULL),
       note=그 시점 팀명, image_path=NULL,
       source_url=해당 구단 위키백과 문서 링크.
     '해체(연도)' 처리: 직전 era 의 valid_to_year=해체연도-1 로 닫고,
       해체 자체는 별도 era 로 만들지 않으며 직전 era note 에 "(해체 YYYY)" 표기.
     단일 토큰 내 범위/해체("쌍방울 레이더스(1991~1999, 해체)") 도 동일하게
       valid_to_year=종료연도, note 에 해체 표기.

  B) NPB/MLB — lineage 에 연도 경계가 없다(추측 금지).
     현재 정체성 1개 era 만 만든다.
       logo_type='primary', valid_from_year=founded_year(있으면, MLB 는 NULL 허용),
       valid_to_year=NULL, note=현재 팀명(lineage 마지막 이름; 과거 이름은
       괄호로 함께 보존), image_path=NULL, source_url=위키백과 문서 링크.

사용:
    python -m backend.ingest.sources.logos load
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "baseball.db"
SOURCE = "curated"

# 위키백과 문서 링크 base (이미지 아님 — 출처 포인터).
WIKI_KO = "https://ko.wikipedia.org/wiki/"
WIKI_EN = "https://en.wikipedia.org/wiki/"

# 토큰 파서: "이름(1982)" / "이름(1982~)" / "이름(1991~1999, 해체)" / "해체(2007)"
_TOKEN_RE = re.compile(
    r"^\s*(?P<name>.+?)\s*"
    r"\(\s*(?P<from>\d{4})\s*"
    r"(?:~\s*(?P<to>\d{4})?\s*)?"
    r"(?:,\s*(?P<flag>[^)]*?)\s*)?"
    r"\)\s*$"
)


def _disband_word(s: str | None) -> bool:
    return bool(s) and ("해체" in s)


def parse_kbo_lineage(lineage: str) -> list[dict]:
    """KBO lineage 문자열을 era dict 리스트로 파싱.

    반환 각 dict: {name, from_year, to_year(or None), disbanded(bool)}
    valid_to_year 계산(다음 era-1)은 호출측에서 채운다 — 여기서는 토큰 자체에
    명시된 종료(범위/해체)만 to_year 로 둔다.
    """
    raw_tokens = [t for t in lineage.split("→") if t.strip()]
    eras: list[dict] = []
    for tok in raw_tokens:
        m = _TOKEN_RE.match(tok.strip())
        if not m:
            # 괄호 없는/예외 토큰: 연도 미상 → 추측 금지, note 로만 남기고 skip.
            eras.append(
                {"name": tok.strip(), "from_year": None, "to_year": None,
                 "disbanded": False, "raw": tok.strip()}
            )
            continue
        name = m.group("name").strip()
        from_year = int(m.group("from"))
        to_year = int(m.group("to")) if m.group("to") else None
        flag = m.group("flag")
        disbanded = _disband_word(flag) or name == "해체"
        eras.append(
            {"name": name, "from_year": from_year, "to_year": to_year,
             "disbanded": disbanded, "raw": tok.strip()}
        )
    return eras


def kbo_logo_rows(franchise_id: int, lineage: str) -> list[dict]:
    """KBO 프랜차이즈 lineage → team_logo 행 리스트(연도 경계 정확히)."""
    eras = parse_kbo_lineage(lineage)

    # '해체(연도)' 단독 토큰을 직전 era 종료로 흡수.
    merged: list[dict] = []
    for e in eras:
        if e["name"] == "해체" and merged:
            prev = merged[-1]
            disband_year = e["from_year"]
            if disband_year is not None:
                prev["to_year"] = disband_year - 1
                prev["disband_year"] = disband_year
            prev["disbanded"] = True
            continue
        # 토큰 내부 범위/해체("1991~1999, 해체"): 종료연도는 to_year 가 명시.
        # 해체연도는 추측하지 않는다(종료연도 != 해체연도일 수 있음) → note 는 "(해체)".
        merged.append(e)

    rows: list[dict] = []
    n = len(merged)
    for i, e in enumerate(merged):
        if e["from_year"] is None:
            # 연도 미상 era — 추측 금지. skip(메타 보존은 lineage 가 이미 가짐).
            continue
        valid_from = e["from_year"]
        # valid_to: 토큰에 명시 종료가 있으면 그것, 아니면 다음 era 시작-1, 없으면 NULL.
        if e["to_year"] is not None:
            valid_to = e["to_year"]
        elif i + 1 < n and merged[i + 1]["from_year"] is not None:
            valid_to = merged[i + 1]["from_year"] - 1
        else:
            valid_to = None

        note = e["name"]
        if e.get("disbanded"):
            dy = e.get("disband_year")
            note = f"{e['name']} (해체 {dy})" if dy else f"{e['name']} (해체)"

        rows.append(
            {
                "franchise_id": franchise_id,
                "logo_type": "primary",
                "valid_from_year": valid_from,
                "valid_to_year": valid_to,
                "image_path": None,
                "source_url": WIKI_KO + e["name"].replace(" ", "_"),
                "note": note,
            }
        )
    return rows


def baseline_logo_rows(
    franchise_id: int, league: str, lineage: str | None, founded_year: int | None
) -> list[dict]:
    """NPB/MLB baseline era 1개 — 연도 경계 추측 금지."""
    names = [n.strip() for n in (lineage or "").split("→") if n.strip()]
    current = names[-1] if names else (lineage or "").strip()
    if len(names) > 1:
        # 과거 이름들을 괄호로 함께 보존(연도 경계는 만들지 않음).
        past = " → ".join(names[:-1])
        note = f"{current} (이전: {past})"
    else:
        note = current

    wiki = WIKI_EN + current.replace(" ", "_")
    return [
        {
            "franchise_id": franchise_id,
            "logo_type": "primary",
            "valid_from_year": founded_year,
            "valid_to_year": None,
            "image_path": None,
            "source_url": wiki,
            "note": note,
        }
    ]


def build_rows(franchises: list[dict]) -> list[dict]:
    """franchise 행 리스트 → team_logo 행 리스트."""
    rows: list[dict] = []
    for f in franchises:
        league = f["league"]
        lineage = f["lineage"]
        if league == "KBO" and lineage:
            rows.extend(kbo_logo_rows(f["id"], lineage))
        else:
            rows.extend(
                baseline_logo_rows(f["id"], league, lineage, f["founded_year"])
            )
    return rows


def load(db_path: str | None = None) -> None:
    """전체 franchise 순회하며 team_logo 멱등 적재."""
    from backend.ingest.load.loader import connect, upsert

    conn = connect(str(db_path or DEFAULT_DB))
    cur = conn.cursor()

    franchises = [
        dict(r)
        for r in cur.execute(
            "SELECT id, league, code, lineage, founded_year FROM franchise"
        ).fetchall()
    ]

    rows = build_rows(franchises)

    # valid_from_year 가 NULL 인 행(MLB: founded_year NULL)은 SQLite UNIQUE 인덱스가
    # NULL 을 서로 다른 값으로 취급해 ON CONFLICT 가 발동하지 않는다 → 재실행마다
    # 중복 INSERT 로 행이 늘어난다. 008 마이그레이션은 수정 금지이므로,
    # NULL from_year 행은 멱등성을 위해 (franchise_id, logo_type) 기준으로 먼저
    # 삭제한 뒤 INSERT 한다(franchise 당 baseline primary 는 1행뿐이라 안전).
    null_rows = [r for r in rows if r["valid_from_year"] is None]
    keyed_rows = [r for r in rows if r["valid_from_year"] is not None]

    for r in null_rows:
        cur.execute(
            "DELETE FROM team_logo "
            "WHERE franchise_id=? AND logo_type=? AND valid_from_year IS NULL",
            (r["franchise_id"], r["logo_type"]),
        )
    conn.commit()
    if null_rows:
        # INSERT (conflict 키가 NULL 을 구분하므로 위 DELETE 후엔 충돌 없음).
        upsert(
            conn,
            "team_logo",
            null_rows,
            conflict_cols=["franchise_id", "logo_type", "valid_from_year"],
            update_cols=["valid_to_year", "image_path", "source_url", "note"],
        )

    # 연도 경계가 있는 행(KBO 모든 era, NPB baseline)은 정상 멱등 upsert.
    upsert(
        conn,
        "team_logo",
        keyed_rows,
        conflict_cols=["franchise_id", "logo_type", "valid_from_year"],
        update_cols=["valid_to_year", "image_path", "source_url", "note"],
    )

    # ---- 요약 ----
    total = cur.execute("SELECT count(*) FROM team_logo").fetchone()[0]
    print(f"load done. team_logo total={total}")
    print("-- rows by league --")
    for r in cur.execute(
        "SELECT f.league, count(*) n FROM team_logo tl "
        "JOIN franchise f ON tl.franchise_id=f.id GROUP BY f.league ORDER BY f.league"
    ):
        print(f"   {r['league']}: {r['n']}")

    img_nonnull = cur.execute(
        "SELECT count(*) FROM team_logo WHERE image_path IS NOT NULL"
    ).fetchone()[0]
    src_null = cur.execute(
        "SELECT count(*) FROM team_logo WHERE source_url IS NULL"
    ).fetchone()[0]
    print(f"-- copyright check: image_path NOT NULL={img_nonnull} (must be 0), "
          f"source_url NULL={src_null} (should be 0)")

    print("-- KBO sample eras --")
    for code in ("WO", "KIA", "HD", "SB"):
        print(f"   [{code}]")
        for r in cur.execute(
            "SELECT tl.valid_from_year vf, tl.valid_to_year vt, tl.note, tl.source_url "
            "FROM team_logo tl JOIN franchise f ON tl.franchise_id=f.id "
            "WHERE f.code=? AND f.league='KBO' ORDER BY tl.valid_from_year",
            (code,),
        ):
            print(f"      {r['vf']}~{r['vt'] if r['vt'] is not None else ''}  "
                  f"{r['note']}  | {r['source_url']}")

    conn.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("load")
    pl.add_argument("--db")
    a = p.parse_args()
    if a.cmd == "load":
        load(db_path=a.db)
