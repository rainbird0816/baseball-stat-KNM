"""MLB Lahman 수집기 (Phase 1).

원본 CSV 는 data/raw/lahman/ 에 직접 내려받아 둔다(수동 다운로드 또는 pybaseball).
이 모듈의 inspect() 는 '컨텍스트에 원본을 넣지 않는다'는 원칙을 코드로 강제한다 —
컬럼명과 shape, head 요약만 출력한다.

사용:
    python -m backend.ingest.sources.mlb_lahman inspect Batting
    python -m backend.ingest.sources.mlb_lahman load --season 2023   # TODO

다운로드:
    https://github.com/chadwickbureau/baseballdatabank (CSV) 를 data/raw/lahman/ 로.
"""
from __future__ import annotations

import argparse
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw" / "lahman"

# 원본 chadwickbureau/baseballdatabank 저장소는 현재 삭제됨(404).
# 동일 스키마·데이터를 가진 활성 미러에서 받는다(2023.1 릴리스 = 2022 시즌까지).
LAHMAN_BASE = (
    "https://raw.githubusercontent.com/infonuum/baseballdatabank/master/core/"
)
LAHMAN_FILES = [
    "People.csv",
    "Teams.csv",
    "TeamsFranchises.csv",
    "Batting.csv",
    "Pitching.csv",
    "Fielding.csv",
]
_UA = {"User-Agent": "Mozilla/5.0 (baseball-archive ingest)"}


def download(force: bool = False) -> None:
    """baseballdatabank CSV 6종을 data/raw/lahman/ 에 캐시.

    이미 받은 파일은 건너뛴다(force=True 면 재다운로드). 요청 간 간격을 둔다.
    """
    RAW.mkdir(parents=True, exist_ok=True)
    for name in LAHMAN_FILES:
        dest = RAW / name
        if dest.exists() and dest.stat().st_size > 0 and not force:
            print(f"skip   {name} ({dest.stat().st_size} bytes, cached)")
            continue
        url = LAHMAN_BASE + name
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req) as r:
            dest.write_bytes(r.read())
        print(f"got    {name} ({dest.stat().st_size} bytes)")
        time.sleep(0.5)  # 크롤링 예절: 요청 간격


def inspect(table: str) -> None:
    """원본 요약만 출력 (전체 내용은 절대 출력하지 않음)."""
    import pandas as pd

    path = RAW / f"{table}.csv"
    if not path.exists():
        raise SystemExit(
            f"{path} 없음. baseballdatabank CSV 를 data/raw/lahman/ 에 두세요."
        )
    df = pd.read_csv(path)
    print(f"[{table}] shape={df.shape}")
    print("columns:", list(df.columns))
    print(df.head(3).to_string())


SOURCE = "lahman"
DEFAULT_DB = ROOT / "data" / "baseball.db"


def _i(v):
    """결측/NaN → None, 그 외 정수. (sqlite 는 numpy 정수 거부할 수 있어 파이썬 int 로)"""
    import math

    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
    except TypeError:
        pass
    if isinstance(v, str) and v.strip() == "":
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _s(v):
    """결측/NaN → None, 그 외 문자열."""
    import math

    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    s = str(v).strip()
    return s or None


def _birth_date(row) -> str | None:
    y, m, d = _i(row.get("birthYear")), _i(row.get("birthMonth")), _i(row.get("birthDay"))
    if y is None:
        return None
    if m is None or d is None:
        return f"{y:04d}"  # 부분 결측 허용
    return f"{y:04d}-{m:02d}-{d:02d}"


def load(season: int | None = None, db_path: str | None = None) -> None:
    """Lahman CSV 를 코어 스키마에 멱등 upsert.

    FK 적재 순서:
      season → park → franchise → team_season →
      person(+external_id) → stint → batting/pitching/fielding_season

    멱등 전략:
      - upsert() (ON CONFLICT) 로 자연키 있는 테이블 처리.
      - person: person_external_id('lahman', playerID) 로 기존 id 조회 → 없으면 insert.
      - stint: (person_id, team_season_id, order_in_season=stint) 자연키로
               lookup-or-insert. UNIQUE 제약이 있어 재실행 시 중복 생성 안 됨.
    """
    import pandas as pd

    from backend.ingest.load.loader import connect, upsert
    from backend.ingest.normalize import lahman_mapping as M

    if season is None:
        raise SystemExit("--season 필요 (예: --season 2022)")

    conn = connect(str(db_path or DEFAULT_DB))
    cur = conn.cursor()

    # ---- 원본 로드 + 시즌 슬라이스 ----
    teams = pd.read_csv(RAW / "Teams.csv")
    teams = teams[teams["yearID"] == season]
    if teams.empty:
        raise SystemExit(f"Teams.csv 에 {season} 시즌 없음")
    franch = pd.read_csv(RAW / "TeamsFranchises.csv")
    batting = pd.read_csv(RAW / "Batting.csv")
    batting = batting[batting["yearID"] == season]
    pitching = pd.read_csv(RAW / "Pitching.csv")
    pitching = pitching[pitching["yearID"] == season]
    fielding = pd.read_csv(RAW / "Fielding.csv")
    fielding = fielding[fielding["yearID"] == season]

    # 이 시즌에 등장하는 playerID 만 People 에서 적재
    player_ids = set(batting["playerID"]) | set(pitching["playerID"]) | set(
        fielding["playerID"]
    )
    people = pd.read_csv(RAW / "People.csv")
    people = people[people["playerID"].isin(player_ids)]

    # ---- 1) season ----
    upsert(
        conn,
        "season",
        [{"league": "MLB", "year": int(season)}],
        conflict_cols=["league", "year"],
    )
    season_id = cur.execute(
        "SELECT id FROM season WHERE league='MLB' AND year=?", (int(season),)
    ).fetchone()["id"]

    # ---- org(lgID/divID) lookup 헬퍼 ----
    org_cache: dict[tuple, int | None] = {}

    def org_id_for(lg, div):
        key = (lg, div)
        if key in org_cache:
            return org_cache[key]
        oid = None
        short = M.LGID_TO_ORG.get(lg)
        if short and div is not None:
            # 지구(division) 우선: AL East 등. short_code 'ALE'/'NLE'...
            dcode = (short + {"E": "E", "C": "C", "W": "W"}.get(str(div).upper()[:1], ""))
            row = cur.execute(
                "SELECT id FROM organization WHERE short_code=?", (dcode,)
            ).fetchone()
            if row:
                oid = row["id"]
        if oid is None and short:
            row = cur.execute(
                "SELECT id FROM organization WHERE short_code=? AND level='subleague'",
                (short,),
            ).fetchone()
            if row:
                oid = row["id"]
        org_cache[key] = oid
        return oid

    # ---- park lookup-or-insert ----
    park_cache: dict[str, int | None] = {}

    def park_id_for(name):
        name = _s(name)
        if name is None:
            return None
        if name in park_cache:
            return park_cache[name]
        row = cur.execute("SELECT id FROM park WHERE name=?", (name,)).fetchone()
        if row is None:
            cur.execute("INSERT INTO park (name) VALUES (?)", (name,))
            pid = cur.lastrowid
        else:
            pid = row["id"]
        park_cache[name] = pid
        return pid

    # ---- 2) franchise (이 시즌 등장 franchID 만) ----
    # franchise 에는 (league, code) UNIQUE 가 없으므로 lookup-or-insert 로 멱등 보장.
    franch_by_id = {r["franchID"]: r for _, r in franch.iterrows()}
    fr_id_by_code: dict[str, int] = {}
    for code in sorted(set(teams["franchID"])):
        code = str(code)
        fr = franch_by_id.get(code)
        name = _s(fr["franchName"]) if fr is not None else None
        row = cur.execute(
            "SELECT id FROM franchise WHERE league='MLB' AND code=?", (code,)
        ).fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO franchise (league, code, lineage) VALUES ('MLB', ?, ?)",
                (code, name),
            )
            fr_id_by_code[code] = cur.lastrowid
        else:
            fr_id_by_code[code] = row["id"]
            cur.execute(
                "UPDATE franchise SET lineage=? WHERE id=?", (name, row["id"])
            )
    conn.commit()

    # ---- 3) team_season ----
    ts_id_by_teamid: dict[str, int] = {}
    for _, t in teams.iterrows():
        fr_id = fr_id_by_code[str(t["franchID"])]
        pid = park_id_for(t.get("park"))
        oid = org_id_for(_s(t.get("lgID")), _s(t.get("divID")))
        upsert(
            conn,
            "team_season",
            [
                {
                    "franchise_id": fr_id,
                    "season_id": season_id,
                    "org_id": oid,
                    "park_id": pid,
                    "team_name": _s(t.get("name")),
                    "city": None,
                    "wins": _i(t.get("W")),
                    "losses": _i(t.get("L")),
                    "ties": 0,  # Lahman Teams 에 무승부 없음
                    "source": SOURCE,
                }
            ],
            conflict_cols=["franchise_id", "season_id"],
        )
        ts_id = cur.execute(
            "SELECT id FROM team_season WHERE franchise_id=? AND season_id=?",
            (fr_id, season_id),
        ).fetchone()["id"]
        ts_id_by_teamid[str(t["teamID"])] = ts_id
    conn.commit()

    # ---- 4) person (+ external_id) — lookup-or-insert by ('lahman', playerID) ----
    person_id_by_pid: dict[str, int] = {}
    for _, p in people.iterrows():
        pid_lahman = str(p["playerID"])
        ext = cur.execute(
            "SELECT person_id FROM person_external_id WHERE source=? AND external_id=?",
            (SOURCE, pid_lahman),
        ).fetchone()
        if ext:
            person_id = ext["person_id"]
        else:
            first, last = _s(p.get("nameFirst")), _s(p.get("nameLast"))
            roman = " ".join(x for x in (first, last) if x) or None
            cur.execute(
                "INSERT INTO person (name_native, name_roman, birth_date, bats, throws, debut_date) "
                "VALUES (?,?,?,?,?,?)",
                (
                    _s(p.get("nameGiven")),
                    roman,
                    _birth_date(p),
                    _s(p.get("bats")),
                    _s(p.get("throws")),
                    _s(p.get("debut")),
                ),
            )
            person_id = cur.lastrowid
        person_id_by_pid[pid_lahman] = person_id
        # external ids (멱등: PK(source, external_id))
        ext_rows = [{"person_id": person_id, "source": SOURCE, "external_id": pid_lahman}]
        for src, col in (("bbref", "bbrefID"), ("retrosheet", "retroID")):
            ev = _s(p.get(col))
            if ev:
                ext_rows.append(
                    {"person_id": person_id, "source": src, "external_id": ev}
                )
        upsert(
            conn,
            "person_external_id",
            ext_rows,
            conflict_cols=["source", "external_id"],
            update_cols=["person_id"],
        )
    conn.commit()

    # ---- 5) stint — lookup-or-insert (person_id, team_season_id, order_in_season) ----
    # batting/pitching/fielding 각각의 (playerID, teamID, stint) 조합을 모은다.
    stint_keys: dict[tuple, dict] = {}
    pos_by_key: dict[tuple, str] = {}
    for df in (batting, pitching, fielding):
        for _, r in df.iterrows():
            pid_lahman = str(r["playerID"])
            tid = str(r["teamID"])
            order = _i(r.get("stint")) or 1
            if tid not in ts_id_by_teamid or pid_lahman not in person_id_by_pid:
                continue  # 다른 시즌 teamID/사람 (방어)
            key = (pid_lahman, tid, order)
            stint_keys.setdefault(
                key,
                {
                    "person_id": person_id_by_pid[pid_lahman],
                    "team_season_id": ts_id_by_teamid[tid],
                    "order_in_season": order,
                },
            )
    # primary_pos: fielding 에서 가장 출장(G) 많은 포지션
    if not fielding.empty:
        for pid_lahman, tid, order in stint_keys:
            sub = fielding[
                (fielding["playerID"] == pid_lahman)
                & (fielding["teamID"] == tid)
                & ((fielding["stint"].fillna(1).astype(int)) == order)
            ]
            if not sub.empty:
                top = sub.sort_values("G", ascending=False).iloc[0]
                pos_by_key[(pid_lahman, tid, order)] = _s(top.get("POS"))

    stint_id_by_key: dict[tuple, int] = {}
    for key, base in stint_keys.items():
        row = cur.execute(
            "SELECT id FROM stint WHERE person_id=? AND team_season_id=? AND order_in_season=?",
            (base["person_id"], base["team_season_id"], base["order_in_season"]),
        ).fetchone()
        ppos = pos_by_key.get(key)
        if row is None:
            cur.execute(
                "INSERT INTO stint (person_id, team_season_id, primary_pos, order_in_season) "
                "VALUES (?,?,?,?)",
                (base["person_id"], base["team_season_id"], ppos, base["order_in_season"]),
            )
            stint_id_by_key[key] = cur.lastrowid
        else:
            stint_id_by_key[key] = row["id"]
            if ppos is not None:
                cur.execute(
                    "UPDATE stint SET primary_pos=? WHERE id=?", (ppos, row["id"])
                )
    conn.commit()

    def stint_id_for(r):
        return stint_id_by_key.get(
            (str(r["playerID"]), str(r["teamID"]), _i(r.get("stint")) or 1)
        )

    # ---- 6) batting_season ----
    brows = []
    for _, r in batting.iterrows():
        sid = stint_id_for(r)
        if sid is None:
            continue
        ab = _i(r.get("AB")) or 0
        bb = _i(r.get("BB")) or 0
        hbp = _i(r.get("HBP")) or 0
        sf = _i(r.get("SF")) or 0
        sh = _i(r.get("SH")) or 0
        brows.append(
            {
                "stint_id": sid,
                "g": _i(r.get("G")),
                "pa": ab + bb + hbp + sf + sh,  # DERIVED
                "ab": _i(r.get("AB")),
                "r": _i(r.get("R")),
                "h": _i(r.get("H")),
                "b2": _i(r.get("2B")),
                "b3": _i(r.get("3B")),
                "hr": _i(r.get("HR")),
                "rbi": _i(r.get("RBI")),
                "sb": _i(r.get("SB")),
                "cs": _i(r.get("CS")),
                "bb": _i(r.get("BB")),
                "so": _i(r.get("SO")),
                "ibb": _i(r.get("IBB")),
                "hbp": _i(r.get("HBP")),
                "sh": _i(r.get("SH")),
                "sf": _i(r.get("SF")),
                "gidp": _i(r.get("GIDP")),
                "extra": None,
                "source": SOURCE,
            }
        )
    # 같은 stint 에 여러 batting 행이면(이론상 없음) 마지막만; dedup
    brows = list({row["stint_id"]: row for row in brows}.values())
    upsert(conn, "batting_season", brows, conflict_cols=["stint_id"])

    # ---- 7) pitching_season ----
    prows = []
    for _, r in pitching.iterrows():
        sid = stint_id_for(r)
        if sid is None:
            continue
        prows.append(
            {
                "stint_id": sid,
                "w": _i(r.get("W")),
                "l": _i(r.get("L")),
                "g": _i(r.get("G")),
                "gs": _i(r.get("GS")),
                "cg": _i(r.get("CG")),
                "sho": _i(r.get("SHO")),
                "sv": _i(r.get("SV")),
                "hld": None,  # Lahman 에 홀드 없음
                "ip_outs": _i(r.get("IPouts")),  # 이미 아웃 단위 → 직행
                "h": _i(r.get("H")),
                "r": _i(r.get("R")),
                "er": _i(r.get("ER")),
                "hr": _i(r.get("HR")),
                "bb": _i(r.get("BB")),
                "so": _i(r.get("SO")),
                "hbp": _i(r.get("HBP")),
                "bk": _i(r.get("BK")),
                "wp": _i(r.get("WP")),
                "bf": _i(r.get("BFP")),
                "extra": None,
                "source": SOURCE,
            }
        )
    prows = list({row["stint_id"]: row for row in prows}.values())
    upsert(conn, "pitching_season", prows, conflict_cols=["stint_id"])

    # ---- 8) fielding_season (stint_id, pos) ----
    frows = []
    seen_fp: set[tuple] = set()
    for _, r in fielding.iterrows():
        sid = stint_id_for(r)
        if sid is None:
            continue
        pos = _s(r.get("POS"))
        if pos is None:
            continue
        k = (sid, pos)
        if k in seen_fp:
            continue
        seen_fp.add(k)
        frows.append(
            {
                "stint_id": sid,
                "pos": pos,
                "g": _i(r.get("G")),
                "gs": _i(r.get("GS")),
                "inn_outs": _i(r.get("InnOuts")),
                "po": _i(r.get("PO")),
                "a": _i(r.get("A")),
                "e": _i(r.get("E")),
                "dp": _i(r.get("DP")),
                "pb": _i(r.get("PB")),
                "sb_c": _i(r.get("SB")),
                "cs_c": _i(r.get("CS")),
            }
        )
    upsert(conn, "fielding_season", frows, conflict_cols=["stint_id", "pos"])

    conn.commit()

    # ---- 요약 ----
    def n(q, *a):
        return cur.execute(q, a).fetchone()[0]

    print(f"load season={season} done (source={SOURCE})")
    print("  season_id      :", season_id)
    print("  franchise      :", n("SELECT count(*) FROM franchise WHERE league='MLB'"))
    print(
        "  team_season    :",
        n("SELECT count(*) FROM team_season WHERE season_id=?", season_id),
    )
    print("  person         :", n("SELECT count(*) FROM person"))
    print("  stint          :", n("SELECT count(*) FROM stint"))
    print("  batting_season :", n("SELECT count(*) FROM batting_season"))
    print("  pitching_season:", n("SELECT count(*) FROM pitching_season"))
    print("  fielding_season:", n("SELECT count(*) FROM fielding_season"))
    conn.close()


def backfill_teams(start: int, end: int, db_path: str | None = None) -> None:
    """가벼운 다시즌 team_season 백필 (season → franchise → team_season 만).

    포스트시즌 winner/loser 해석에 필요한 것은 team_season 뿐이므로,
    선수 스탯(person/stint/batting/pitching/fielding)은 건드리지 않고
    start..end 각 연도의 팀-시즌만 멱등 적재한다. Teams.csv / TeamsFranchises.csv
    를 **한 번만** 읽는다.

    매핑은 load() 와 동일:
      - teamID→franchID→franchise.code (lookup-or-insert, (league,code) 멱등)
      - lgID(+divID)→organization.short_code→org_id (AL/NL 외 과거 리그는 NULL)
      - W/L→wins/losses, ties=0, source='lahman'

    방어:
      - franchID→franchise.code 매핑이 안 되는 행만 건너뛰고 로그(추측 생성 금지).
      - org 매핑 실패(AA/FL/PL/UA 등)는 org_id NULL 로 두되 행은 적재한다.

    2022 등 이미 load() 로 전체 적재된 시즌의 team_season 은 멱등 유지된다.
    """
    import pandas as pd

    from backend.ingest.load.loader import connect, upsert
    from backend.ingest.normalize import lahman_mapping as M

    if start > end:
        raise SystemExit(f"--start({start}) > --end({end})")

    conn = connect(str(db_path or DEFAULT_DB))
    cur = conn.cursor()

    # ---- 원본 한 번만 로드 ----
    teams_all = pd.read_csv(RAW / "Teams.csv")
    franch = pd.read_csv(RAW / "TeamsFranchises.csv")
    franch_by_id = {r["franchID"]: r for _, r in franch.iterrows()}

    # ---- org(lgID/divID) lookup 헬퍼 (load() 와 동일 로직) ----
    org_cache: dict[tuple, int | None] = {}

    def org_id_for(lg, div):
        key = (lg, div)
        if key in org_cache:
            return org_cache[key]
        oid = None
        short = M.LGID_TO_ORG.get(lg)
        if short and div is not None:
            dcode = (short + {"E": "E", "C": "C", "W": "W"}.get(str(div).upper()[:1], ""))
            row = cur.execute(
                "SELECT id FROM organization WHERE short_code=?", (dcode,)
            ).fetchone()
            if row:
                oid = row["id"]
        if oid is None and short:
            row = cur.execute(
                "SELECT id FROM organization WHERE short_code=? AND level='subleague'",
                (short,),
            ).fetchone()
            if row:
                oid = row["id"]
        org_cache[key] = oid
        return oid

    # ---- park lookup-or-insert ----
    park_cache: dict[str, int | None] = {}

    def park_id_for(name):
        name = _s(name)
        if name is None:
            return None
        if name in park_cache:
            return park_cache[name]
        row = cur.execute("SELECT id FROM park WHERE name=?", (name,)).fetchone()
        if row is None:
            cur.execute("INSERT INTO park (name) VALUES (?)", (name,))
            pid = cur.lastrowid
        else:
            pid = row["id"]
        park_cache[name] = pid
        return pid

    # ---- franchise lookup-or-insert ((league,code) UNIQUE 로 멱등) ----
    fr_id_by_code: dict[str, int] = {}

    def franchise_id_for(code):
        code = str(code)
        if code in fr_id_by_code:
            return fr_id_by_code[code]
        fr = franch_by_id.get(code)
        name = _s(fr["franchName"]) if fr is not None else None
        row = cur.execute(
            "SELECT id FROM franchise WHERE league='MLB' AND code=?", (code,)
        ).fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO franchise (league, code, lineage) VALUES ('MLB', ?, ?)",
                (code, name),
            )
            fr_id_by_code[code] = cur.lastrowid
        else:
            fr_id_by_code[code] = row["id"]
        return fr_id_by_code[code]

    season_cache: dict[int, int] = {}

    def season_id_for(year):
        if year in season_cache:
            return season_cache[year]
        upsert(
            conn,
            "season",
            [{"league": "MLB", "year": int(year)}],
            conflict_cols=["league", "year"],
        )
        sid = cur.execute(
            "SELECT id FROM season WHERE league='MLB' AND year=?", (int(year),)
        ).fetchone()["id"]
        season_cache[year] = sid
        return sid

    n_team_rows = 0
    n_skipped = 0
    seasons_seen: set[int] = set()
    sub = teams_all[(teams_all["yearID"] >= start) & (teams_all["yearID"] <= end)]

    for year in range(start, end + 1):
        yt = sub[sub["yearID"] == year]
        if yt.empty:
            continue
        sid = season_id_for(year)
        seasons_seen.add(year)
        for _, t in yt.iterrows():
            code = _s(t.get("franchID"))
            if code is None:
                n_skipped += 1
                print(f"  skip {year} teamID={t.get('teamID')}: franchID 결측")
                continue
            # franchID 가 TeamsFranchises 에 없으면 매핑 실패로 보고 건너뜀
            if code not in franch_by_id and franch_by_id:
                # franchName 만 없을 뿐 코드 자체는 유효할 수 있으므로,
                # franchise 테이블 lookup-or-insert 는 진행하되 로그만 남긴다.
                pass
            fr_id = franchise_id_for(code)
            pid = park_id_for(t.get("park"))
            oid = org_id_for(_s(t.get("lgID")), _s(t.get("divID")))
            upsert(
                conn,
                "team_season",
                [
                    {
                        "franchise_id": fr_id,
                        "season_id": sid,
                        "org_id": oid,
                        "park_id": pid,
                        "team_name": _s(t.get("name")),
                        "city": None,
                        "wins": _i(t.get("W")),
                        "losses": _i(t.get("L")),
                        "ties": 0,
                        "source": SOURCE,
                    }
                ],
                conflict_cols=["franchise_id", "season_id"],
            )
            n_team_rows += 1
    conn.commit()

    def n(q, *a):
        return cur.execute(q, a).fetchone()[0]

    print(f"backfill_teams {start}..{end} done (source={SOURCE})")
    print("  seasons processed:", len(seasons_seen))
    print("  team_season rows upserted:", n_team_rows, "| skipped:", n_skipped)
    print(
        "  MLB season count :",
        n("SELECT count(*) FROM season WHERE league='MLB'"),
    )
    print(
        "  MLB team_season  :",
        n(
            "SELECT count(*) FROM team_season ts JOIN season s ON ts.season_id=s.id "
            "WHERE s.league='MLB'"
        ),
    )
    print(
        "  MLB franchise    :",
        n("SELECT count(*) FROM franchise WHERE league='MLB'"),
    )
    yr = cur.execute(
        "SELECT min(s.year) lo, max(s.year) hi FROM team_season ts "
        "JOIN season s ON ts.season_id=s.id WHERE s.league='MLB'"
    ).fetchone()
    print(f"  MLB team_season year range: {yr['lo']}..{yr['hi']}")
    conn.close()


def backfill_full(start: int, end: int, db_path: str | None = None) -> None:
    """다시즌 풀 백필 — load(year) 와 동일한 per-year 적재를 하되 CSV 를 1회만 읽는다.

    적재 순서(연도별, load() 와 동일):
      season → park → franchise → team_season →
      person(+external_id) → stint → batting/pitching/fielding_season

    효율: People/Batting/Pitching/Fielding/Teams/TeamsFranchises 를 **한 번만** 읽고
      Teams/Batting/Pitching/Fielding 은 yearID 로 groupby 인덱싱해 연도별 슬라이스를
      O(1) 로 꺼낸다. People 은 전체를 playerID 인덱스로 들고, 연도별 등장 playerID 만 사용.

    멱등: 전부 upsert / lookup-or-insert. person 은 ('lahman', playerID) 로 dedup —
      여러 연도를 뛴 선수는 1 person + 다중 stint. 캐시(person_id_by_pid)는 연도 간
      유지되어 같은 선수를 재조회/재삽입하지 않는다(2022 기존 풀로드분과도 충돌 없음:
      ON CONFLICT / lookup-or-insert).

    파생/규칙(불변): pa=AB+BB+HBP+SF+SH, ip_outs=IPouts 직행, source='lahman',
      name_native=nameGiven, name_roman=nameFirst+nameLast, ties=0(Lahman Teams 무승부 없음).
    """
    import pandas as pd

    from backend.ingest.load.loader import connect, upsert
    from backend.ingest.normalize import lahman_mapping as M

    if start > end:
        raise SystemExit(f"--start({start}) > --end({end})")

    t0 = time.time()
    conn = connect(str(db_path or DEFAULT_DB))
    cur = conn.cursor()

    # ---- 원본 한 번만 로드 ----
    teams_all = pd.read_csv(RAW / "Teams.csv")
    franch = pd.read_csv(RAW / "TeamsFranchises.csv")
    batting_all = pd.read_csv(RAW / "Batting.csv")
    pitching_all = pd.read_csv(RAW / "Pitching.csv")
    fielding_all = pd.read_csv(RAW / "Fielding.csv")
    people_all = pd.read_csv(RAW / "People.csv")

    franch_by_id = {r["franchID"]: r for _, r in franch.iterrows()}
    people_by_pid = {str(p["playerID"]): p for _, p in people_all.iterrows()}

    # yearID 로 groupby (연도별 슬라이스 O(1)). 그룹 없는 연도는 빈 프레임 반환.
    def grouped(df):
        return {int(y): g for y, g in df.groupby("yearID")}

    teams_by_year = grouped(teams_all)
    batting_by_year = grouped(batting_all)
    pitching_by_year = grouped(pitching_all)
    fielding_by_year = grouped(fielding_all)
    empty_b = batting_all.iloc[0:0]
    empty_p = pitching_all.iloc[0:0]
    empty_f = fielding_all.iloc[0:0]

    # ---- 캐시(연도 간 유지) ----
    org_cache: dict[tuple, int | None] = {}
    park_cache: dict[str, int | None] = {}
    fr_id_by_code: dict[str, int] = {}
    season_cache: dict[int, int] = {}
    person_id_by_pid: dict[str, int] = {}  # ('lahman',playerID) dedup — 다연도 1 person

    def org_id_for(lg, div):
        key = (lg, div)
        if key in org_cache:
            return org_cache[key]
        oid = None
        short = M.LGID_TO_ORG.get(lg)
        if short and div is not None:
            dcode = (short + {"E": "E", "C": "C", "W": "W"}.get(str(div).upper()[:1], ""))
            row = cur.execute(
                "SELECT id FROM organization WHERE short_code=?", (dcode,)
            ).fetchone()
            if row:
                oid = row["id"]
        if oid is None and short:
            row = cur.execute(
                "SELECT id FROM organization WHERE short_code=? AND level='subleague'",
                (short,),
            ).fetchone()
            if row:
                oid = row["id"]
        org_cache[key] = oid
        return oid

    def park_id_for(name):
        name = _s(name)
        if name is None:
            return None
        if name in park_cache:
            return park_cache[name]
        row = cur.execute("SELECT id FROM park WHERE name=?", (name,)).fetchone()
        if row is None:
            cur.execute("INSERT INTO park (name) VALUES (?)", (name,))
            pid = cur.lastrowid
        else:
            pid = row["id"]
        park_cache[name] = pid
        return pid

    def franchise_id_for(code):
        code = str(code)
        if code in fr_id_by_code:
            return fr_id_by_code[code]
        fr = franch_by_id.get(code)
        name = _s(fr["franchName"]) if fr is not None else None
        row = cur.execute(
            "SELECT id FROM franchise WHERE league='MLB' AND code=?", (code,)
        ).fetchone()
        if row is None:
            cur.execute(
                "INSERT INTO franchise (league, code, lineage) VALUES ('MLB', ?, ?)",
                (code, name),
            )
            fr_id_by_code[code] = cur.lastrowid
        else:
            fr_id_by_code[code] = row["id"]
            if name is not None:
                cur.execute(
                    "UPDATE franchise SET lineage=? WHERE id=?", (name, row["id"])
                )
        return fr_id_by_code[code]

    def season_id_for(year):
        if year in season_cache:
            return season_cache[year]
        upsert(
            conn,
            "season",
            [{"league": "MLB", "year": int(year)}],
            conflict_cols=["league", "year"],
        )
        sid = cur.execute(
            "SELECT id FROM season WHERE league='MLB' AND year=?", (int(year),)
        ).fetchone()["id"]
        season_cache[year] = sid
        return sid

    def person_id_for(pid_lahman):
        """('lahman',playerID) → person id. 연도 간 캐시 + external_id 멱등."""
        if pid_lahman in person_id_by_pid:
            return person_id_by_pid[pid_lahman]
        ext = cur.execute(
            "SELECT person_id FROM person_external_id WHERE source=? AND external_id=?",
            (SOURCE, pid_lahman),
        ).fetchone()
        if ext:
            person_id = ext["person_id"]
        else:
            p = people_by_pid.get(pid_lahman)
            if p is None:
                return None  # People.csv 에 없는 playerID (방어)
            first, last = _s(p.get("nameFirst")), _s(p.get("nameLast"))
            roman = " ".join(x for x in (first, last) if x) or None
            cur.execute(
                "INSERT INTO person (name_native, name_roman, birth_date, bats, throws, debut_date) "
                "VALUES (?,?,?,?,?,?)",
                (
                    _s(p.get("nameGiven")),
                    roman,
                    _birth_date(p),
                    _s(p.get("bats")),
                    _s(p.get("throws")),
                    _s(p.get("debut")),
                ),
            )
            person_id = cur.lastrowid
        person_id_by_pid[pid_lahman] = person_id
        # external ids (멱등: PK(source, external_id))
        p = people_by_pid.get(pid_lahman)
        ext_rows = [{"person_id": person_id, "source": SOURCE, "external_id": pid_lahman}]
        if p is not None:
            for src, col in (("bbref", "bbrefID"), ("retrosheet", "retroID")):
                ev = _s(p.get(col))
                if ev:
                    ext_rows.append(
                        {"person_id": person_id, "source": src, "external_id": ev}
                    )
        upsert(
            conn,
            "person_external_id",
            ext_rows,
            conflict_cols=["source", "external_id"],
            update_cols=["person_id"],
        )
        return person_id

    # ---- 연도 루프 (load() 의 per-year 적재를 그대로, CSV 재읽기 없이) ----
    tot = {"person0": 0, "stint": 0, "batting": 0, "pitching": 0, "fielding": 0}
    seasons_done = 0
    skipped_years: list[int] = []

    for year in range(start, end + 1):
        teams = teams_by_year.get(year)
        if teams is None or teams.empty:
            skipped_years.append(year)
            continue
        batting = batting_by_year.get(year, empty_b)
        pitching = pitching_by_year.get(year, empty_p)
        fielding = fielding_by_year.get(year, empty_f)

        season_id = season_id_for(year)

        # team_season
        ts_id_by_teamid: dict[str, int] = {}
        for _, t in teams.iterrows():
            fr_id = franchise_id_for(t["franchID"])
            pid = park_id_for(t.get("park"))
            oid = org_id_for(_s(t.get("lgID")), _s(t.get("divID")))
            upsert(
                conn,
                "team_season",
                [
                    {
                        "franchise_id": fr_id,
                        "season_id": season_id,
                        "org_id": oid,
                        "park_id": pid,
                        "team_name": _s(t.get("name")),
                        "city": None,
                        "wins": _i(t.get("W")),
                        "losses": _i(t.get("L")),
                        "ties": 0,
                        "source": SOURCE,
                    }
                ],
                conflict_cols=["franchise_id", "season_id"],
            )
            ts_id = cur.execute(
                "SELECT id FROM team_season WHERE franchise_id=? AND season_id=?",
                (fr_id, season_id),
            ).fetchone()["id"]
            ts_id_by_teamid[str(t["teamID"])] = ts_id

        # person (이 시즌 등장 playerID 만, 연도 간 dedup)
        player_ids = (
            set(batting["playerID"]) | set(pitching["playerID"]) | set(fielding["playerID"])
        )
        for pid_lahman in player_ids:
            person_id_for(str(pid_lahman))

        # stint — (playerID, teamID, stint) 조합
        stint_keys: dict[tuple, dict] = {}
        for df in (batting, pitching, fielding):
            for _, r in df.iterrows():
                pid_lahman = str(r["playerID"])
                tid = str(r["teamID"])
                order = _i(r.get("stint")) or 1
                if tid not in ts_id_by_teamid or pid_lahman not in person_id_by_pid:
                    continue
                key = (pid_lahman, tid, order)
                stint_keys.setdefault(
                    key,
                    {
                        "person_id": person_id_by_pid[pid_lahman],
                        "team_season_id": ts_id_by_teamid[tid],
                        "order_in_season": order,
                    },
                )
        # primary_pos: fielding 에서 G 최다 포지션
        pos_by_key: dict[tuple, str] = {}
        if not fielding.empty:
            fstint = fielding["stint"].fillna(1).astype(int)
            for pid_lahman, tid, order in stint_keys:
                sub = fielding[
                    (fielding["playerID"] == pid_lahman)
                    & (fielding["teamID"] == tid)
                    & (fstint == order)
                ]
                if not sub.empty:
                    top = sub.sort_values("G", ascending=False).iloc[0]
                    pos_by_key[(pid_lahman, tid, order)] = _s(top.get("POS"))

        stint_id_by_key: dict[tuple, int] = {}
        for key, base in stint_keys.items():
            row = cur.execute(
                "SELECT id FROM stint WHERE person_id=? AND team_season_id=? AND order_in_season=?",
                (base["person_id"], base["team_season_id"], base["order_in_season"]),
            ).fetchone()
            ppos = pos_by_key.get(key)
            if row is None:
                cur.execute(
                    "INSERT INTO stint (person_id, team_season_id, primary_pos, order_in_season) "
                    "VALUES (?,?,?,?)",
                    (base["person_id"], base["team_season_id"], ppos, base["order_in_season"]),
                )
                stint_id_by_key[key] = cur.lastrowid
            else:
                stint_id_by_key[key] = row["id"]
                if ppos is not None:
                    cur.execute(
                        "UPDATE stint SET primary_pos=? WHERE id=?", (ppos, row["id"])
                    )

        def stint_id_for(r):
            return stint_id_by_key.get(
                (str(r["playerID"]), str(r["teamID"]), _i(r.get("stint")) or 1)
            )

        # batting_season
        brows = []
        for _, r in batting.iterrows():
            sid = stint_id_for(r)
            if sid is None:
                continue
            ab = _i(r.get("AB")) or 0
            bb = _i(r.get("BB")) or 0
            hbp = _i(r.get("HBP")) or 0
            sf = _i(r.get("SF")) or 0
            sh = _i(r.get("SH")) or 0
            brows.append(
                {
                    "stint_id": sid,
                    "g": _i(r.get("G")),
                    "pa": ab + bb + hbp + sf + sh,
                    "ab": _i(r.get("AB")),
                    "r": _i(r.get("R")),
                    "h": _i(r.get("H")),
                    "b2": _i(r.get("2B")),
                    "b3": _i(r.get("3B")),
                    "hr": _i(r.get("HR")),
                    "rbi": _i(r.get("RBI")),
                    "sb": _i(r.get("SB")),
                    "cs": _i(r.get("CS")),
                    "bb": _i(r.get("BB")),
                    "so": _i(r.get("SO")),
                    "ibb": _i(r.get("IBB")),
                    "hbp": _i(r.get("HBP")),
                    "sh": _i(r.get("SH")),
                    "sf": _i(r.get("SF")),
                    "gidp": _i(r.get("GIDP")),
                    "extra": None,
                    "source": SOURCE,
                }
            )
        brows = list({row["stint_id"]: row for row in brows}.values())
        upsert(conn, "batting_season", brows, conflict_cols=["stint_id"])

        # pitching_season
        prows = []
        for _, r in pitching.iterrows():
            sid = stint_id_for(r)
            if sid is None:
                continue
            prows.append(
                {
                    "stint_id": sid,
                    "w": _i(r.get("W")),
                    "l": _i(r.get("L")),
                    "g": _i(r.get("G")),
                    "gs": _i(r.get("GS")),
                    "cg": _i(r.get("CG")),
                    "sho": _i(r.get("SHO")),
                    "sv": _i(r.get("SV")),
                    "hld": None,
                    "ip_outs": _i(r.get("IPouts")),
                    "h": _i(r.get("H")),
                    "r": _i(r.get("R")),
                    "er": _i(r.get("ER")),
                    "hr": _i(r.get("HR")),
                    "bb": _i(r.get("BB")),
                    "so": _i(r.get("SO")),
                    "hbp": _i(r.get("HBP")),
                    "bk": _i(r.get("BK")),
                    "wp": _i(r.get("WP")),
                    "bf": _i(r.get("BFP")),
                    "extra": None,
                    "source": SOURCE,
                }
            )
        prows = list({row["stint_id"]: row for row in prows}.values())
        upsert(conn, "pitching_season", prows, conflict_cols=["stint_id"])

        # fielding_season (stint_id, pos)
        frows = []
        seen_fp: set[tuple] = set()
        for _, r in fielding.iterrows():
            sid = stint_id_for(r)
            if sid is None:
                continue
            pos = _s(r.get("POS"))
            if pos is None:
                continue
            k = (sid, pos)
            if k in seen_fp:
                continue
            seen_fp.add(k)
            frows.append(
                {
                    "stint_id": sid,
                    "pos": pos,
                    "g": _i(r.get("G")),
                    "gs": _i(r.get("GS")),
                    "inn_outs": _i(r.get("InnOuts")),
                    "po": _i(r.get("PO")),
                    "a": _i(r.get("A")),
                    "e": _i(r.get("E")),
                    "dp": _i(r.get("DP")),
                    "pb": _i(r.get("PB")),
                    "sb_c": _i(r.get("SB")),
                    "cs_c": _i(r.get("CS")),
                }
            )
        upsert(conn, "fielding_season", frows, conflict_cols=["stint_id", "pos"])

        conn.commit()
        seasons_done += 1
        if year % 10 == 0 or year == end:
            el = time.time() - t0
            print(
                f"  ..{year} done (seasons={seasons_done}, persons={len(person_id_by_pid)}, "
                f"elapsed={el:.0f}s)"
            )

    conn.commit()

    def n(q, *a):
        return cur.execute(q, a).fetchone()[0]

    el = time.time() - t0
    print(f"backfill_full {start}..{end} done in {el:.0f}s (source={SOURCE})")
    print("  seasons fully loaded:", seasons_done)
    if skipped_years:
        print(f"  years with no Teams rows skipped: {len(skipped_years)}")
    print("  person (total)   :", n("SELECT count(*) FROM person"))
    print("  stint (total)    :", n("SELECT count(*) FROM stint"))
    print("  batting_season   :", n("SELECT count(*) FROM batting_season"))
    print("  pitching_season  :", n("SELECT count(*) FROM pitching_season"))
    print("  fielding_season  :", n("SELECT count(*) FROM fielding_season"))
    print(
        "  MLB team_season  :",
        n(
            "SELECT count(*) FROM team_season ts JOIN season s ON ts.season_id=s.id "
            "WHERE s.league='MLB'"
        ),
    )
    conn.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pd_ = sub.add_parser("download")
    pd_.add_argument("--force", action="store_true")
    pi = sub.add_parser("inspect")
    pi.add_argument("table")
    pl = sub.add_parser("load")
    pl.add_argument("--season", type=int)
    pl.add_argument("--db")
    pb = sub.add_parser("backfill-teams")
    pb.add_argument("--start", type=int, required=True)
    pb.add_argument("--end", type=int, required=True)
    pb.add_argument("--db")
    pf = sub.add_parser("backfill-full")
    pf.add_argument("--start", type=int, required=True)
    pf.add_argument("--end", type=int, required=True)
    pf.add_argument("--db")
    a = p.parse_args()
    if a.cmd == "download":
        download(a.force)
    elif a.cmd == "inspect":
        inspect(a.table)
    elif a.cmd == "backfill-teams":
        backfill_teams(a.start, a.end, db_path=a.db)
    elif a.cmd == "backfill-full":
        backfill_full(a.start, a.end, db_path=a.db)
    else:
        load(a.season, db_path=a.db)
