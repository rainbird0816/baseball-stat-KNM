"""우승 시리즈 & 보조 데이터 수집기 (Phase 6).

월드시리즈/일본시리즈/한국시리즈를 postseason_series 에 적재하고,
MLB 수상 투표 지분(award_share)을 채운다. is_championship=1 로 최종
우승 결정전을 표시하고, 가능하면 mvp_person_id 를 연결한다.

데이터 출처
  - MLB 포스트시즌 시리즈: Lahman SeriesPost.csv (core/)         source='lahman'
  - MLB WS MVP / 수상 투표 : Lahman AwardsPlayers / AwardsSharePlayers (contrib/)
  - NPB/KBO 우승 시리즈    : 모듈 상수 CHAMPIONSHIPS (큐레이션)         source='curated'

불변 규칙
  - 원본 CSV 는 inspect() 요약으로만 본다(전체 컨텍스트 금지).
  - 멱등 upsert (loader.upsert). 재실행해도 행이 늘지 않는다.
  - 우리 team_season 이 있는 시즌만 연결한다: MLB 는 backfill 된 전 연도(1903~2022 등),
    NPB 2021/2022, KBO 2024.
  - 추측으로 person 을 생성하지 않는다. MVP 미해석 시 mvp_person_id=NULL + 로그.

사용:
    python -m backend.ingest.sources.postseason download
    python -m backend.ingest.sources.postseason inspect SeriesPost
    python -m backend.ingest.sources.postseason load
"""
from __future__ import annotations

import argparse
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw" / "lahman"
DEFAULT_DB = ROOT / "data" / "baseball.db"
SOURCE_MLB = "lahman"
SOURCE_CURATED = "curated"

# baseballdatabank 활성 미러(infonuum, 2023.1 릴리스).
#  - core/      : SeriesPost.csv (2022 시즌까지 포함)
#  - contrib/   : AwardsPlayers.csv / AwardsSharePlayers.csv
#    (주의: 현재 모든 공개 미러의 contrib Awards 는 갱신이 늦다 —
#     AwardsPlayers 는 2021, AwardsSharePlayers 는 2016 까지만 존재.
#     따라서 2022 WS MVP / 2022 수상 투표 원본은 공개 소스에 없다.
#     로더는 존재하는 행만 멱등 적재하고, 없으면 빈 결과로 보고한다.)
_CORE_BASE = "https://raw.githubusercontent.com/infonuum/baseballdatabank/master/core/"
_CONTRIB_BASE = (
    "https://raw.githubusercontent.com/infonuum/baseballdatabank/master/contrib/"
)
LAHMAN_FILES = {
    "SeriesPost.csv": _CORE_BASE,
    "AwardsPlayers.csv": _CONTRIB_BASE,
    "AwardsSharePlayers.csv": _CONTRIB_BASE,
    # 매핑용으로 mlb_lahman.download() 가 이미 받아둔 Teams.csv 를 재사용한다.
}
_UA = {"User-Agent": "Mozilla/5.0 (baseball-archive ingest)"}

# ---- award 정규화: Lahman awardID → 우리 award 코드 ----
_AWARD_MAP = {
    "MVP": "MVP",
    "Cy Young": "CyYoung",
    "Rookie of the Year": "RookieOfYear",
}
# Lahman AwardsPlayers 의 World Series MVP 표기
_WS_MVP_AWARD = "World Series MVP"


# MLB 2022 주요 수상 (큐레이션 — 공개 미러 Awards 가 2021/2016까지라 원본 없음).
# 확정된 공개 사실만. won=1, vote_pct=NULL(투표 지분 미상).
# person 해석: name_roman 정확 일치 우선, 실패 시 ('lahman', playerID) 후보.
# DB 에 실제 존재하는 것만 적재. 못 찾으면 1건 skip + 로그(추측 person 생성 금지).
MLB_AWARDS_2022 = [
    {"award": "MVP",          "name_roman": "Aaron Judge",       "player_id": "judgeaa01"},
    {"award": "MVP",          "name_roman": "Paul Goldschmidt",  "player_id": "goldspa01"},
    {"award": "CyYoung",      "name_roman": "Justin Verlander",  "player_id": "verlaju01"},
    {"award": "CyYoung",      "name_roman": "Sandy Alcantara",   "player_id": "alcansa01"},
    {"award": "RookieOfYear", "name_roman": "Julio Rodriguez",   "player_id": "rodriju01"},
    {"award": "RookieOfYear", "name_roman": "Michael Harris",    "player_id": "harrimi04"},
]
# MLB 2022 WS MVP (큐레이션). Jeremy Pena (Houston Astros).
MLB_WS_MVP_2022 = {"name_roman": "Jeremy Pena", "player_id": "penaje02"}


# NPB/KBO 우승 시리즈 (Lahman 에 없음 — 큐레이션).
# winner/loser 는 (league, franchise.code, year) → team_season 으로 해석.
# mvp_native 는 해당 리그 person.name_native(공백 무시) 매칭. 없으면 NULL + 로그.
CHAMPIONSHIPS = [
    {
        "league": "NPB",
        "year": 2021,
        "round": "JapanSeries",
        "winner_code": "YS",   # 도쿄 야쿠르트 스왈로즈
        "loser_code": "ORX",   # 오릭스 버펄로스
        "wins": 4, "losses": 2, "ties": 1,
        "mvp_native": "中村悠平",
    },
    {
        "league": "NPB",
        "year": 2022,
        "round": "JapanSeries",
        "winner_code": "ORX",
        "loser_code": "YS",
        "wins": 4, "losses": 2, "ties": 1,
        "mvp_native": "杉本裕太郎",
    },
    {
        "league": "KBO",
        "year": 2024,
        "round": "KoreanSeries",
        "winner_code": "KIA",
        "loser_code": "SS",    # 삼성 라이온즈
        "wins": 4, "losses": 1, "ties": 0,
        "mvp_native": "김선빈",
    },
]


def download(force: bool = False) -> None:
    """SeriesPost / AwardsPlayers / AwardsSharePlayers 를 data/raw/lahman/ 에 캐시."""
    RAW.mkdir(parents=True, exist_ok=True)
    for name, base in LAHMAN_FILES.items():
        dest = RAW / name
        if dest.exists() and dest.stat().st_size > 0 and not force:
            print(f"skip   {name} ({dest.stat().st_size} bytes, cached)")
            continue
        req = urllib.request.Request(base + name, headers=_UA)
        with urllib.request.urlopen(req) as r:
            dest.write_bytes(r.read())
        print(f"got    {name} ({dest.stat().st_size} bytes)")
        time.sleep(0.5)
    # Teams.csv 는 mlb_lahman.download() 가 받아둔다 — 매핑에 필요하니 확인만.
    if not (RAW / "Teams.csv").exists():
        print("warn   Teams.csv 없음 — `mlb_lahman download` 먼저 실행 필요(2022 매핑용).")


def inspect(table: str) -> None:
    """원본 요약만 출력(전체 내용 금지)."""
    import pandas as pd

    path = RAW / f"{table}.csv"
    if not path.exists():
        raise SystemExit(f"{path} 없음. `postseason download` 먼저 실행.")
    df = pd.read_csv(path)
    print(f"[{table}] shape={df.shape}")
    print("columns:", list(df.columns))
    print(df.head(3).to_string())


def _norm_native(s: str | None) -> str:
    """name_native 비교용 정규화: 공백 제거(BIS 표는 '中村 悠平' 처럼 공백 포함)."""
    if s is None:
        return ""
    return "".join(str(s).split())


def load(db_path: str | None = None) -> None:
    """B(SeriesPost 2022) + C(award_share 2022) + D(NPB/KBO 큐레이션) 멱등 적재."""
    import pandas as pd

    from backend.ingest.load.loader import connect, upsert

    conn = connect(str(db_path or DEFAULT_DB))
    cur = conn.cursor()

    def season_id(league: str, year: int) -> int | None:
        row = cur.execute(
            "SELECT id FROM season WHERE league=? AND year=?", (league, year)
        ).fetchone()
        return row["id"] if row else None

    def ts_id(league: str, code: str, year: int) -> int | None:
        row = cur.execute(
            "SELECT ts.id FROM team_season ts "
            "JOIN franchise f ON ts.franchise_id=f.id "
            "JOIN season s ON ts.season_id=s.id "
            "WHERE f.league=? AND f.code=? AND s.year=?",
            (league, code, year),
        ).fetchone()
        return row["id"] if row else None

    def mlb_person(player_id: str) -> int | None:
        row = cur.execute(
            "SELECT person_id FROM person_external_id WHERE source='lahman' AND external_id=?",
            (player_id,),
        ).fetchone()
        return row["person_id"] if row else None

    def roman_person(name_roman: str) -> int | None:
        """name_roman 정확 일치하는 첫 person id(동명이인 시 첫 행)."""
        row = cur.execute(
            "SELECT id FROM person WHERE name_roman=? ORDER BY id", (name_roman,)
        ).fetchone()
        return row["id"] if row else None

    def resolve_mlb_person(name_roman: str, player_id: str) -> int | None:
        """name_roman 정확 일치 우선, 실패 시 ('lahman', playerID) 후보."""
        pid = roman_person(name_roman)
        if pid is not None:
            return pid
        return mlb_person(player_id)

    def native_person(league: str, native: str) -> int | None:
        """리그 person 중 name_native(공백 무시) 일치하는 첫 person id."""
        target = _norm_native(native)
        if not target:
            return None
        rows = cur.execute(
            "SELECT DISTINCT p.id, p.name_native FROM person p "
            "JOIN person_external_id pe ON pe.person_id=p.id "
            "WHERE pe.source=?",
            (league.lower(),),
        ).fetchall()
        for r in rows:
            if _norm_native(r["name_native"]) == target:
                return r["id"]
        return None

    log: list[str] = []

    # =========================================================
    # B) MLB 포스트시즌 (SeriesPost) — 전 연도 일반화
    #    team_season(winner/loser) 이 둘 다 해석되는 연도/시리즈만 적재.
    # =========================================================
    sid_mlb_2022 = season_id("MLB", 2022)  # C/E 단계(2022 수상 큐레이션)에서 재사용
    series_rows: list[dict] = []

    sp_path = RAW / "SeriesPost.csv"
    teams_path = RAW / "Teams.csv"
    if not sp_path.exists() or not teams_path.exists():
        log.append("SeriesPost.csv / Teams.csv 없음 — MLB 포스트시즌 skip")
    else:
        sp = pd.read_csv(sp_path)
        teams = pd.read_csv(teams_path)
        # (year, teamID) → franchID 매핑 (teamID 는 연도별로 재사용되므로 연도 포함)
        teamid_to_franch: dict[tuple, str] = {
            (int(yr), str(tid)): str(fr)
            for yr, tid, fr in zip(
                teams["yearID"], teams["teamID"], teams["franchID"]
            )
        }

        # WS MVP: AwardsPlayers 의 'World Series MVP' 를 연도별로 인덱싱(있는 연도만).
        ws_mvp_by_year: dict[int, str] = {}
        ap_path = RAW / "AwardsPlayers.csv"
        if ap_path.exists():
            ap = pd.read_csv(ap_path)
            ws = ap[ap["awardID"] == _WS_MVP_AWARD]
            for _, a in ws.iterrows():
                ws_mvp_by_year[int(a["yearID"])] = str(a["playerID"])

        # season_id 캐시(연도별 1회 조회)
        sid_cache: dict[int, int | None] = {}

        def mlb_sid(year: int) -> int | None:
            if year not in sid_cache:
                sid_cache[year] = season_id("MLB", year)
            return sid_cache[year]

        resolved_years: set[int] = set()
        skipped_years: set[int] = set()
        for _, r in sp.iterrows():
            year = int(r["yearID"])
            sid = mlb_sid(year)
            if sid is None:
                skipped_years.add(year)  # team_season 미적재 연도
                continue
            rnd = str(r["round"])
            w_franch = teamid_to_franch.get((year, str(r["teamIDwinner"])))
            l_franch = teamid_to_franch.get((year, str(r["teamIDloser"])))
            w_ts = ts_id("MLB", w_franch, year) if w_franch else None
            l_ts = ts_id("MLB", l_franch, year) if l_franch else None
            if w_ts is None or l_ts is None:
                log.append(
                    f"MLB {year} {rnd}: ts 미해석 "
                    f"(winner={r['teamIDwinner']}->{w_franch}/{w_ts}, "
                    f"loser={r['teamIDloser']}->{l_franch}/{l_ts}) → skip"
                )
                continue
            is_champ = 1 if rnd == "WS" else 0
            out_round = "WorldSeries" if rnd == "WS" else rnd
            mvp_pid = None
            if is_champ:
                mvp_playerid = ws_mvp_by_year.get(year)
                if mvp_playerid is not None:
                    mvp_pid = mlb_person(mvp_playerid)
            series_rows.append(
                {
                    "season_id": sid,
                    "league": "MLB",
                    "round": out_round,
                    "is_championship": is_champ,
                    "winner_ts_id": w_ts,
                    "loser_ts_id": l_ts,
                    "wins": int(r["wins"]),
                    "losses": int(r["losses"]),
                    "ties": int(r["ties"]) if not pd.isna(r["ties"]) else 0,
                    "mvp_person_id": mvp_pid,
                    "source": SOURCE_MLB,
                }
            )
            resolved_years.add(year)
        if skipped_years:
            log.append(
                f"MLB SeriesPost: team_season 미적재 {len(skipped_years)}개 연도 skip "
                f"(예 {sorted(skipped_years)[:5]}...)"
            )
        if resolved_years:
            log.append(
                f"MLB SeriesPost: {len(resolved_years)}개 연도 해석 "
                f"({min(resolved_years)}~{max(resolved_years)})"
            )

    # =========================================================
    # C) MLB 2022 수상 투표 (award_share, AwardsSharePlayers)
    # =========================================================
    award_rows: list[dict] = []
    ash_path = RAW / "AwardsSharePlayers.csv"
    if sid_mlb_2022 is not None and ash_path.exists():
        ash = pd.read_csv(ash_path)
        ash = ash[(ash["yearID"] == 2022) & (ash["awardID"].isin(_AWARD_MAP))]
        if ash.empty:
            log.append(
                "MLB 2022 award_share 원본 없음(공개 AwardsSharePlayers 는 2016까지) "
                "→ award_share 0행"
            )
        else:
            # won: (awardID, lgID) 그룹 내 pointsWon 최댓값이면 1
            max_pts = (
                ash.groupby(["awardID", "lgID"])["pointsWon"].transform("max")
            )
            for (_, r), mx in zip(ash.iterrows(), max_pts):
                pid = mlb_person(str(r["playerID"]))
                if pid is None:
                    log.append(
                        f"MLB 2022 award_share {r['awardID']} "
                        f"playerID={r['playerID']} person 미해석 → skip"
                    )
                    continue
                pmax = r["pointsMax"]
                vote_pct = (
                    float(r["pointsWon"]) / float(pmax)
                    if pmax and not pd.isna(pmax) and float(pmax) != 0
                    else None
                )
                award_rows.append(
                    {
                        "person_id": pid,
                        "season_id": sid_mlb_2022,
                        "award": _AWARD_MAP[str(r["awardID"])],
                        "vote_pct": vote_pct,
                        "won": 1 if float(r["pointsWon"]) >= float(mx) else 0,
                    }
                )

    # =========================================================
    # D) NPB/KBO 우승 시리즈 (큐레이션)
    # =========================================================
    for c in CHAMPIONSHIPS:
        lg, yr = c["league"], c["year"]
        sid = season_id(lg, yr)
        if sid is None:
            log.append(f"{lg} {yr} season 없음 — {c['round']} skip")
            continue
        w_ts = ts_id(lg, c["winner_code"], yr)
        l_ts = ts_id(lg, c["loser_code"], yr)
        if w_ts is None or l_ts is None:
            log.append(
                f"{lg} {yr} {c['round']}: ts 미해석 "
                f"(winner {c['winner_code']}={w_ts}, loser {c['loser_code']}={l_ts}) → skip"
            )
            continue
        mvp_pid = native_person(lg, c["mvp_native"])
        if mvp_pid is None:
            log.append(
                f"{lg} {yr} {c['round']} MVP '{c['mvp_native']}' person 미해석 "
                f"→ mvp_person_id NULL"
            )
        series_rows.append(
            {
                "season_id": sid,
                "league": lg,
                "round": c["round"],
                "is_championship": 1,
                "winner_ts_id": w_ts,
                "loser_ts_id": l_ts,
                "wins": c["wins"],
                "losses": c["losses"],
                "ties": c["ties"],
                "mvp_person_id": mvp_pid,
                "source": SOURCE_CURATED,
            }
        )

    # =========================================================
    # E) MLB 2022 수상 큐레이션 (award_share 보강 + WS MVP 보강)
    #    공개 미러 Awards 가 2021/2016까지라 C 단계가 비므로 큐레이션으로 채운다.
    # =========================================================
    ws_mvp_set = False
    if sid_mlb_2022 is None:
        log.append("MLB 2022 season 없음 — 2022 수상 큐레이션 skip")
    else:
        for a in MLB_AWARDS_2022:
            pid = resolve_mlb_person(a["name_roman"], a["player_id"])
            if pid is None:
                log.append(
                    f"MLB 2022 큐레이션 {a['award']} '{a['name_roman']}'"
                    f"(playerID={a['player_id']}) person 미해석 → skip"
                )
                continue
            award_rows.append(
                {
                    "person_id": pid,
                    "season_id": sid_mlb_2022,
                    "award": a["award"],
                    "vote_pct": None,
                    "won": 1,
                }
            )

        # WS 2022 MVP 보강 — postseason_series (MLB, 2022, WorldSeries) 행 UPDATE.
        ws_mvp_pid = resolve_mlb_person(
            MLB_WS_MVP_2022["name_roman"], MLB_WS_MVP_2022["player_id"]
        )
        if ws_mvp_pid is None:
            log.append(
                f"MLB 2022 WS MVP 큐레이션 '{MLB_WS_MVP_2022['name_roman']}' "
                "person 미해석 → mvp_person_id NULL 유지"
            )
        else:
            # series_rows 의 WorldSeries 행이 있으면 그쪽에 채워 upsert 가 반영.
            for sr in series_rows:
                if (
                    sr["season_id"] == sid_mlb_2022
                    and sr["round"] == "WorldSeries"
                ):
                    sr["mvp_person_id"] = ws_mvp_pid
                    ws_mvp_set = True

    # =========================================================
    # 멱등 적재
    # =========================================================
    upsert(
        conn,
        "postseason_series",
        series_rows,
        conflict_cols=["season_id", "league", "round"],
        update_cols=[
            "is_championship", "winner_ts_id", "loser_ts_id",
            "wins", "losses", "ties", "mvp_person_id", "source",
        ],
    )
    upsert(
        conn,
        "award_share",
        award_rows,
        conflict_cols=["person_id", "season_id", "award"],
        update_cols=["vote_pct", "won"],
    )
    # WS 2022 MVP 보강 fallback: series_rows 가 재생성되지 않은 경우라도
    # 기존 WorldSeries 행을 직접 UPDATE 한다(멱등).
    if not ws_mvp_set and sid_mlb_2022 is not None:
        wpid = resolve_mlb_person(
            MLB_WS_MVP_2022["name_roman"], MLB_WS_MVP_2022["player_id"]
        )
        if wpid is not None:
            cur.execute(
                "UPDATE postseason_series SET mvp_person_id=? "
                "WHERE season_id=? AND league='MLB' AND round='WorldSeries'",
                (wpid, sid_mlb_2022),
            )
            ws_mvp_set = True
    conn.commit()

    # =========================================================
    # 요약
    # =========================================================
    def champ_label(r):
        win = cur.execute(
            "SELECT team_name FROM team_season WHERE id=?", (r["winner_ts_id"],)
        ).fetchone()
        win_name = win["team_name"] if win else "?"
        mvp = "MVP있음" if r["mvp_person_id"] is not None else "MVP없음"
        return (
            f"{r['league']}/{r['round']}: {win_name} "
            f"{r['wins']}-{r['losses']}-{r['ties']} ({mvp})"
        )

    n_series = cur.execute("SELECT count(*) FROM postseason_series").fetchone()[0]
    n_award = cur.execute("SELECT count(*) FROM award_share").fetchone()[0]
    print(f"load done. postseason_series={n_series}, award_share={n_award}")
    print("-- championships (is_championship=1) --")
    champ_rows = cur.execute(
        "SELECT * FROM postseason_series WHERE is_championship=1 "
        "ORDER BY league, season_id"
    ).fetchall()
    for r in champ_rows:
        print("  ", champ_label(r))
    print("-- award_share by award (won=1 count) --")
    for r in cur.execute(
        "SELECT award, count(*) n, sum(won) won1 FROM award_share GROUP BY award"
    ):
        print(f"   {r['award']}: {r['n']}건, won=1 {r['won1']}명")
    if log:
        print("-- notes --")
        for ln in log:
            print("  *", ln)
    conn.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pd_ = sub.add_parser("download")
    pd_.add_argument("--force", action="store_true")
    pi = sub.add_parser("inspect")
    pi.add_argument("table")
    pl = sub.add_parser("load")
    pl.add_argument("--db")
    a = p.parse_args()
    if a.cmd == "download":
        download(a.force)
    elif a.cmd == "inspect":
        inspect(a.table)
    else:
        load(db_path=a.db)
