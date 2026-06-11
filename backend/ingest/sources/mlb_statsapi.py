"""MLB StatsAPI 경기 단위(T2) 수집기 (Phase 2).

공개·무키 엔드포인트 statsapi.mlb.com 만 사용한다.
원본 JSON 응답은 data/raw/statsapi/<date>/ 에 캐시한 뒤 재파싱한다(재요청 최소화).

원칙:
  - inspect() 는 구조 요약(키 목록/경기 수/샘플 1건)만 출력 — 원본 통째 출력 금지.
  - 이닝은 아웃 정수(ip_outs). inningsPitched "6.2" -> 6*3+2 = 20.
  - source='statsapi' provenance 항상 기록.
  - 모든 적재는 멱등 upsert (loader.upsert / connect).

teamId 매핑:
  StatsAPI 숫자 teamId -> 우리 franchise.code -> team_season(season=year)

인물 mlbam 연결 전략(우선순위):
  (a) Chadwick register crosswalk: key_bbref -> key_mlbam 로 우리 bbref external_id 와 조인.
  (b) 폴백: people/{id} 의 fullName+birthDate 를 우리 (name_roman, birth_date) 와 정확 매칭.
  (c) 그래도 없으면 신규 person 생성 + mlbam external_id.

사용:
    python -m backend.ingest.sources.mlb_statsapi inspect 2022-04-15
    python -m backend.ingest.sources.mlb_statsapi backfill --start 2022-04-15 --end 2022-04-15
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw" / "statsapi"
DEFAULT_DB = ROOT / "data" / "baseball.db"
SOURCE = "statsapi"

API = "https://statsapi.mlb.com/api/v1"
_UA = {"User-Agent": "Mozilla/5.0 (baseball-archive ingest)"}
_DELAY = 0.4  # 요청 간 폴리트 딜레이(초)

# Chadwick register (key_bbref -> key_mlbam). 16개 샤드.
_REGISTER_BASE = "https://raw.githubusercontent.com/chadwickbureau/register/master/data/"
_REGISTER_SHARDS = [f"people-{c}.csv" for c in "0123456789abcdef"]
_REGISTER_CACHE = RAW / "_register"

# ---------------------------------------------------------------------------
# StatsAPI 숫자 teamId -> 우리 franchise.code (Lahman franchID 스타일)
# 현행 30개 팀(108~121, 133~147). StatsAPI 약어와 우리 코드가 다름에 주의.
# ---------------------------------------------------------------------------
TEAMID_TO_CODE: dict[int, str] = {
    108: "ANA",  # Los Angeles Angels (StatsAPI LAA)
    109: "ARI",  # Arizona Diamondbacks
    110: "BAL",  # Baltimore Orioles
    111: "BOS",  # Boston Red Sox
    112: "CHC",  # Chicago Cubs
    113: "CIN",  # Cincinnati Reds
    114: "CLE",  # Cleveland Guardians
    115: "COL",  # Colorado Rockies
    116: "DET",  # Detroit Tigers
    117: "HOU",  # Houston Astros
    118: "KCR",  # Kansas City Royals (StatsAPI KC)
    119: "LAD",  # Los Angeles Dodgers
    120: "WSN",  # Washington Nationals (StatsAPI WSH)
    121: "NYM",  # New York Mets
    133: "OAK",  # Oakland Athletics
    134: "PIT",  # Pittsburgh Pirates
    135: "SDP",  # San Diego Padres (StatsAPI SD)
    136: "SEA",  # Seattle Mariners
    137: "SFG",  # San Francisco Giants (StatsAPI SF)
    138: "STL",  # St. Louis Cardinals
    139: "TBD",  # Tampa Bay Rays (StatsAPI TB)
    140: "TEX",  # Texas Rangers
    141: "TOR",  # Toronto Blue Jays
    142: "MIN",  # Minnesota Twins
    143: "PHI",  # Philadelphia Phillies
    144: "ATL",  # Atlanta Braves
    145: "CHW",  # Chicago White Sox (StatsAPI CWS)
    146: "FLA",  # Miami Marlins (StatsAPI MIA, Lahman franchID FLA)
    147: "NYY",  # New York Yankees
    158: "MIL",  # Milwaukee Brewers
}


# ---------------------------------------------------------------------------
# HTTP + 캐시
# ---------------------------------------------------------------------------
def _get_json(url: str, cache_path: Path | None = None) -> dict:
    """url 을 GET. cache_path 가 있으면 캐시 우선(있으면 재요청 안 함)."""
    if cache_path and cache_path.exists() and cache_path.stat().st_size > 0:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(data)
    time.sleep(_DELAY)
    return json.loads(data.decode("utf-8"))


def _schedule(date: str) -> list[dict]:
    """해당 날짜(YYYY-MM-DD)의 경기 목록(games[]) 반환."""
    url = f"{API}/schedule?sportId=1&date={date}"
    cache = RAW / date / "schedule.json"
    sched = _get_json(url, cache)
    dates = sched.get("dates", [])
    games: list[dict] = []
    for d in dates:
        games.extend(d.get("games", []))
    return games


def _boxscore(game_pk: int, date: str) -> dict:
    url = f"{API}/game/{game_pk}/boxscore"
    cache = RAW / date / f"box_{game_pk}.json"
    return _get_json(url, cache)


def _people(mlbam_ids: list[int]) -> dict[int, dict]:
    """people/{ids} 일괄 조회(콤마 구분). {id: personObj}."""
    out: dict[int, dict] = {}
    if not mlbam_ids:
        return out
    # StatsAPI 는 personIds 콤마 구분 일괄 조회 지원. 100개씩 끊어 요청.
    for i in range(0, len(mlbam_ids), 100):
        chunk = mlbam_ids[i : i + 100]
        ids = ",".join(str(x) for x in chunk)
        url = f"{API}/people?personIds={ids}"
        cache = _REGISTER_CACHE / f"people_{chunk[0]}_{len(chunk)}.json"
        data = _get_json(url, cache)
        for p in data.get("people", []):
            out[int(p["id"])] = p
    return out


# ---------------------------------------------------------------------------
# 변환 헬퍼
# ---------------------------------------------------------------------------
def ip_to_outs(ip) -> int | None:
    """inningsPitched 문자열/수치 -> 아웃 정수. '6.2' -> 20, '1.0' -> 3."""
    if ip is None:
        return None
    s = str(ip).strip()
    if not s:
        return None
    if "." in s:
        whole, frac = s.split(".", 1)
        frac = frac[:1] or "0"
    else:
        whole, frac = s, "0"
    try:
        return int(whole) * 3 + int(frac)
    except ValueError:
        return None


def _decision(pit: dict) -> str | None:
    """boxscore 투수 stats 의 W/L/S/H 플래그 -> decision 문자열."""
    if pit.get("wins"):
        return "W"
    if pit.get("losses"):
        return "L"
    if pit.get("saves"):
        return "S"
    if pit.get("holds"):
        return "H"
    return None


def _is_final(game: dict) -> bool:
    st = (game.get("status") or {}).get("abstractGameState")
    return st == "Final"


def _status_str(game: dict) -> str:
    return "tie" if game.get("isTie") else "final"


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------
def inspect(date: str) -> None:
    """schedule + 한 경기 boxscore 의 구조 요약만 출력."""
    games = _schedule(date)
    finals = [g for g in games if _is_final(g)]
    print(f"[schedule {date}] games={len(games)} final={len(finals)}")
    if games:
        g = games[0]
        print("game keys:", sorted(g.keys()))
        print(
            f"  gamePk={g['gamePk']} type={g.get('gameType')} "
            f"state={(g.get('status') or {}).get('abstractGameState')} "
            f"isTie={g.get('isTie')}"
        )
        h, a = g["teams"]["home"], g["teams"]["away"]
        print(
            f"  home teamId={h['team'].get('id')} score={h.get('score')} "
            f"isWinner={h.get('isWinner')} | away teamId={a['team'].get('id')} "
            f"score={a.get('score')}"
        )
        print(f"  venue={ (g.get('venue') or {}).get('name') }")
    if not games:
        return
    pk = games[0]["gamePk"]
    box = _boxscore(pk, date)
    print(f"[boxscore {pk}] top keys:", sorted(box.keys()))
    home = box["teams"]["home"]
    print("  team-side keys:", sorted(home.keys()))
    players = home["players"]
    print(f"  home players={len(players)}")
    sample_key = next(iter(players))
    pl = players[sample_key]
    print("  player keys:", sorted(pl.keys()))
    bat = pl.get("stats", {}).get("batting", {})
    print(
        "  sample batting fields present:",
        [
            k
            for k in (
                "plateAppearances",
                "atBats",
                "runs",
                "hits",
                "homeRuns",
                "rbi",
                "baseOnBalls",
                "strikeOuts",
                "stolenBases",
            )
            if k in bat
        ],
    )


# ---------------------------------------------------------------------------
# 인물 mlbam 연결
# ---------------------------------------------------------------------------
def _ensure_register(force: bool = False) -> Path | None:
    """Chadwick register 16샤드를 받아 key_bbref->key_mlbam 만 추린 단일 CSV 캐시.

    실패(오프라인 등) 시 None.
    """
    import csv

    out = _REGISTER_CACHE / "bbref_mlbam.csv"
    if out.exists() and out.stat().st_size > 0 and not force:
        return out
    _REGISTER_CACHE.mkdir(parents=True, exist_ok=True)
    pairs: list[tuple[str, str]] = []
    try:
        for shard in _REGISTER_SHARDS:
            url = _REGISTER_BASE + shard
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                text = r.read().decode("utf-8")
            time.sleep(_DELAY)
            reader = csv.DictReader(text.splitlines())
            for row in reader:
                bb = (row.get("key_bbref") or "").strip()
                mlb = (row.get("key_mlbam") or "").strip()
                if bb and mlb:
                    pairs.append((bb, mlb))
    except Exception as e:  # noqa: BLE001
        print(f"  [register] 다운로드 실패({e}); 폴백(b)/신규(c) 로 진행")
        return None
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["key_bbref", "key_mlbam"])
        w.writerows(pairs)
    print(f"  [register] bbref->mlbam {len(pairs)} 쌍 캐시")
    return out


def _link_persons(conn, mlbam_ids: list[int], year: int) -> dict[int, int]:
    """슬라이스에 등장한 mlbam id -> 우리 person_id 해석.

    이미 mlbam external_id 가 있으면 그대로 사용.
    없으면 (a) register, (b) people 매칭, (c) 신규 생성 순.
    카운트는 print 로 보고.
    """
    import csv

    cur = conn.cursor()
    resolved: dict[int, int] = {}
    counts = {"existing": 0, "register": 0, "fallback": 0, "new": 0}

    # 0) 이미 mlbam external_id 보유분
    remaining: list[int] = []
    for mid in mlbam_ids:
        row = cur.execute(
            "SELECT person_id FROM person_external_id WHERE source='mlbam' AND external_id=?",
            (str(mid),),
        ).fetchone()
        if row:
            resolved[mid] = row["person_id"]
            counts["existing"] += 1
        else:
            remaining.append(mid)

    # (a) register crosswalk: mlbam -> bbref, bbref external_id 로 우리 person 조회
    reg_path = _ensure_register()
    mlbam_to_bbref: dict[str, str] = {}
    if reg_path is not None and remaining:
        wanted = {str(m) for m in remaining}
        with reg_path.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["key_mlbam"] in wanted:
                    mlbam_to_bbref[r["key_mlbam"]] = r["key_bbref"]
        still: list[int] = []
        for mid in remaining:
            bb = mlbam_to_bbref.get(str(mid))
            pid = None
            if bb:
                row = cur.execute(
                    "SELECT person_id FROM person_external_id "
                    "WHERE source='bbref' AND external_id=?",
                    (bb,),
                ).fetchone()
                if row:
                    pid = row["person_id"]
            if pid is not None:
                resolved[mid] = pid
                _add_mlbam(conn, pid, mid)
                counts["register"] += 1
            else:
                still.append(mid)
        remaining = still

    # (b) 폴백: people/{id} fullName+birthDate 정확 매칭
    new_payloads: dict[int, dict] = {}
    if remaining:
        people = _people(remaining)
        still2: list[int] = []
        for mid in remaining:
            p = people.get(mid)
            if not p:
                still2.append(mid)
                continue
            full = p.get("fullName")
            bdate = p.get("birthDate")
            pid = None
            if full and bdate:
                row = cur.execute(
                    "SELECT id FROM person WHERE name_roman=? AND birth_date=?",
                    (full, bdate),
                ).fetchone()
                if row:
                    pid = row["id"]
            if pid is not None:
                resolved[mid] = pid
                _add_mlbam(conn, pid, mid)
                counts["fallback"] += 1
            else:
                still2.append(mid)
                new_payloads[mid] = p
        remaining = still2

    # (c) 신규 person 생성
    for mid in remaining:
        p = new_payloads.get(mid) or {}
        full = p.get("fullName") or f"mlbam:{mid}"
        bats = (p.get("batSide") or {}).get("code")
        throws = (p.get("pitchHand") or {}).get("code")
        cur.execute(
            "INSERT INTO person (name_native, name_roman, birth_date, bats, throws, debut_date) "
            "VALUES (?,?,?,?,?,?)",
            (full, full, p.get("birthDate"), bats, throws, p.get("mlbDebutDate")),
        )
        pid = cur.lastrowid
        resolved[mid] = pid
        _add_mlbam(conn, pid, mid)
        counts["new"] += 1
    conn.commit()

    total_added = counts["register"] + counts["fallback"] + counts["new"]
    print(
        f"  [person link] existing={counts['existing']} register(a)={counts['register']} "
        f"fallback(b)={counts['fallback']} new(c)={counts['new']} "
        f"| mlbam external_id 추가={total_added}"
    )
    return resolved


def _add_mlbam(conn, person_id: int, mlbam_id: int) -> None:
    from backend.ingest.load.loader import upsert

    upsert(
        conn,
        "person_external_id",
        [{"person_id": person_id, "source": "mlbam", "external_id": str(mlbam_id)}],
        conflict_cols=["source", "external_id"],
        update_cols=["person_id"],
    )


# ---------------------------------------------------------------------------
# team_season / park 해석
# ---------------------------------------------------------------------------
def _ts_resolver(conn, year: int):
    cur = conn.cursor()
    cache: dict[int, int | None] = {}

    def resolve(team_id: int) -> int | None:
        if team_id in cache:
            return cache[team_id]
        code = TEAMID_TO_CODE.get(int(team_id))
        ts_id = None
        if code:
            row = cur.execute(
                "SELECT ts.id FROM team_season ts "
                "JOIN franchise f ON f.id=ts.franchise_id "
                "JOIN season se ON se.id=ts.season_id "
                "WHERE f.code=? AND se.year=? AND f.league='MLB'",
                (code, year),
            ).fetchone()
            if row:
                ts_id = row["id"]
        cache[team_id] = ts_id
        return ts_id

    return resolve


def _park_resolver(conn):
    cur = conn.cursor()
    cache: dict[str, int | None] = {}

    def resolve(name: str | None) -> int | None:
        if not name:
            return None
        if name in cache:
            return cache[name]
        row = cur.execute("SELECT id FROM park WHERE name=?", (name,)).fetchone()
        if row is None:
            cur.execute("INSERT INTO park (name) VALUES (?)", (name,))
            pid = cur.lastrowid
        else:
            pid = row["id"]
        cache[name] = pid
        return pid

    return resolve


# ---------------------------------------------------------------------------
# backfill
# ---------------------------------------------------------------------------
def _date_range(start: str, end: str) -> list[str]:
    from datetime import date, timedelta

    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    out = []
    cur = s
    while cur <= e:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def backfill(start: str, end: str, db_path: str | None = None) -> None:
    """start~end 종료(Final) 정규시즌(R) 경기를 멱등 upsert."""
    from backend.ingest.load.loader import connect, upsert

    conn = connect(str(db_path or DEFAULT_DB))
    cur = conn.cursor()

    n_games = n_bat = n_pit = 0
    for date_str in _date_range(start, end):
        year = int(date_str[:4])
        season_row = cur.execute(
            "SELECT id FROM season WHERE league='MLB' AND year=?", (year,)
        ).fetchone()
        if not season_row:
            print(f"[{date_str}] season {year} 미적재 — 건너뜀")
            continue
        season_id = season_row["id"]

        ts_for = _ts_resolver(conn, year)
        park_for = _park_resolver(conn)

        games = _schedule(date_str)
        final_reg = [
            g for g in games if g.get("gameType") == "R" and _is_final(g)
        ]
        print(f"[{date_str}] games={len(games)} final-regular={len(final_reg)}")

        # 슬라이스 전체 박스스코어 미리 받아 등장 mlbam id 수집
        boxes: dict[int, dict] = {}
        mlbam_ids: set[int] = set()
        for g in final_reg:
            pk = g["gamePk"]
            box = _boxscore(pk, date_str)
            boxes[pk] = box
            for side in ("home", "away"):
                for pl in box["teams"][side]["players"].values():
                    pid = pl.get("person", {}).get("id")
                    if pid is not None:
                        mlbam_ids.add(int(pid))

        person_map = _link_persons(conn, sorted(mlbam_ids), year)

        for g in final_reg:
            pk = g["gamePk"]
            box = boxes[pk]
            home_id = g["teams"]["home"]["team"]["id"]
            away_id = g["teams"]["away"]["team"]["id"]
            home_ts = ts_for(home_id)
            away_ts = ts_for(away_id)
            if home_ts is None or away_ts is None:
                print(
                    f"  [skip {pk}] team_season 해석 실패 home={home_id} away={away_id}"
                )
                continue
            venue = (g.get("venue") or {}).get("name")
            park_id = park_for(venue)
            innings = g.get("scheduledInnings")
            # 실제 진행 이닝(연장/단축) 우선: linescore 없이 boxscore 로 근사 — scheduledInnings 사용
            home_score = g["teams"]["home"].get("score")
            away_score = g["teams"]["away"].get("score")

            upsert(
                conn,
                "game",
                [
                    {
                        "league": "MLB",
                        "season_id": season_id,
                        "game_date": date_str,
                        "game_type": "regular",
                        "home_ts_id": home_ts,
                        "away_ts_id": away_ts,
                        "park_id": park_id,
                        "home_score": home_score,
                        "away_score": away_score,
                        "innings": innings,
                        "status": _status_str(g),
                        "source": SOURCE,
                    }
                ],
                conflict_cols=["league", "game_date", "home_ts_id", "away_ts_id"],
            )
            game_id = cur.execute(
                "SELECT id FROM game WHERE league='MLB' AND game_date=? "
                "AND home_ts_id=? AND away_ts_id=?",
                (date_str, home_ts, away_ts),
            ).fetchone()["id"]
            n_games += 1

            bat_rows = []
            pit_rows = []
            for side, ts_id in (("home", home_ts), ("away", away_ts)):
                for pl in box["teams"][side]["players"].values():
                    mid = pl.get("person", {}).get("id")
                    if mid is None:
                        continue
                    person_id = person_map.get(int(mid))
                    if person_id is None:
                        continue
                    stats = pl.get("stats", {})
                    bat = stats.get("batting", {})
                    if bat.get("plateAppearances") or bat.get("atBats"):
                        bat_rows.append(
                            {
                                "game_id": game_id,
                                "person_id": person_id,
                                "team_season_id": ts_id,
                                "pa": bat.get("plateAppearances"),
                                "ab": bat.get("atBats"),
                                "r": bat.get("runs"),
                                "h": bat.get("hits"),
                                "hr": bat.get("homeRuns"),
                                "rbi": bat.get("rbi"),
                                "bb": bat.get("baseOnBalls"),
                                "so": bat.get("strikeOuts"),
                                "sb": bat.get("stolenBases"),
                            }
                        )
                    pit = stats.get("pitching", {})
                    if pit.get("inningsPitched") is not None:
                        pit_rows.append(
                            {
                                "game_id": game_id,
                                "person_id": person_id,
                                "team_season_id": ts_id,
                                "ip_outs": ip_to_outs(pit.get("inningsPitched")),
                                "h": pit.get("hits"),
                                "r": pit.get("runs"),
                                "er": pit.get("earnedRuns"),
                                "bb": pit.get("baseOnBalls"),
                                "so": pit.get("strikeOuts"),
                                "hr": pit.get("homeRuns"),
                                "pitches": pit.get("numberOfPitches")
                                or pit.get("pitchesThrown"),
                                "decision": _decision(pit),
                            }
                        )
            # 같은 (game, person) 중복 방지 dedup
            bat_rows = list(
                {(r["game_id"], r["person_id"]): r for r in bat_rows}.values()
            )
            pit_rows = list(
                {(r["game_id"], r["person_id"]): r for r in pit_rows}.values()
            )
            upsert(
                conn,
                "player_batting_game",
                bat_rows,
                conflict_cols=["game_id", "person_id"],
            )
            upsert(
                conn,
                "player_pitching_game",
                pit_rows,
                conflict_cols=["game_id", "person_id"],
            )
            n_bat += len(bat_rows)
            n_pit += len(pit_rows)

    conn.commit()
    print(
        f"[backfill {start}..{end}] game upsert={n_games} "
        f"batting={n_bat} pitching={n_pit}"
    )
    conn.close()


# ---------------------------------------------------------------------------
# 시즌 스탯(T1) — backfill_season
# ---------------------------------------------------------------------------
SEASON_RAW = RAW / "season"

# 시즌 hitting/pitching split 의 stat 키 -> 코어 컬럼 매핑(실측 inspect 확정).
# StatsAPI 필드명은 people/{id}/stats?stats=season 응답 기준.


def _standings(year: int) -> dict[int, dict]:
    """정규시즌 standings 에서 teamId -> {wins,losses,ties}. 실패 시 빈 dict."""
    url = (
        f"{API}/standings?leagueId=103,104&season={year}"
        "&standingsTypes=regularSeason"
    )
    cache = SEASON_RAW / str(year) / "standings.json"
    try:
        d = _get_json(url, cache)
    except Exception as e:  # noqa: BLE001
        print(f"  [standings] 조회 실패({e}); W/L/T NULL 로 진행")
        return {}
    out: dict[int, dict] = {}
    for rec in d.get("records", []):
        for tr in rec.get("teamRecords", []):
            tid = (tr.get("team") or {}).get("id")
            if tid is None:
                continue
            out[int(tid)] = {
                "wins": tr.get("wins"),
                "losses": tr.get("losses"),
                "ties": tr.get("ties") or 0,
            }
    return out


def _teams_meta(year: int) -> dict[int, str]:
    """teams?sportId=1&season= 에서 teamId -> 풀네임('San Francisco Giants')."""
    url = f"{API}/teams?sportId=1&season={year}"
    cache = SEASON_RAW / str(year) / "teams.json"
    try:
        d = _get_json(url, cache)
    except Exception as e:  # noqa: BLE001
        print(f"  [teams] 조회 실패({e}); team_name 폴백 사용")
        return {}
    return {int(t["id"]): t.get("name") for t in d.get("teams", []) if t.get("id")}


def _season_roster(team_id: int, year: int) -> list[dict]:
    """팀의 fullSeason 로스터(roster[])."""
    url = f"{API}/teams/{team_id}/roster?rosterType=fullSeason&season={year}"
    cache = SEASON_RAW / str(year) / f"roster_{team_id}.json"
    d = _get_json(url, cache)
    return d.get("roster", [])


def _player_season(mlbam_id: int, year: int, group: str) -> list[dict]:
    """people/{id}/stats?stats=season&group= 의 splits[](팀별 분할) 반환."""
    url = (
        f"{API}/people/{mlbam_id}/stats?stats=season&season={year}"
        f"&group={group}&sportId=1"
    )
    cache = SEASON_RAW / str(year) / group / f"p_{mlbam_id}.json"
    d = _get_json(url, cache)
    st = d.get("stats", [])
    if not st:
        return []
    return st[0].get("splits", [])


def _i(v):
    """결측 -> None, 그 외 파이썬 int(sqlite numpy 거부 회피)."""
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _bat_row(stat: dict, stint_id: int) -> dict:
    return {
        "stint_id": stint_id,
        "g": _i(stat.get("gamesPlayed")),
        "pa": _i(stat.get("plateAppearances")),
        "ab": _i(stat.get("atBats")),
        "r": _i(stat.get("runs")),
        "h": _i(stat.get("hits")),
        "b2": _i(stat.get("doubles")),
        "b3": _i(stat.get("triples")),
        "hr": _i(stat.get("homeRuns")),
        "rbi": _i(stat.get("rbi")),
        "sb": _i(stat.get("stolenBases")),
        "cs": _i(stat.get("caughtStealing")),
        "bb": _i(stat.get("baseOnBalls")),
        "so": _i(stat.get("strikeOuts")),
        "ibb": _i(stat.get("intentionalWalks")),
        "hbp": _i(stat.get("hitByPitch")),
        "sh": _i(stat.get("sacBunts")),
        "sf": _i(stat.get("sacFlies")),
        "gidp": _i(stat.get("groundIntoDoublePlay")),
        "extra": None,
        "source": SOURCE,
    }


def _pit_row(stat: dict, stint_id: int) -> dict:
    return {
        "stint_id": stint_id,
        "w": _i(stat.get("wins")),
        "l": _i(stat.get("losses")),
        "g": _i(stat.get("gamesPitched")),
        "gs": _i(stat.get("gamesStarted")),
        "cg": _i(stat.get("completeGames")),
        "sho": _i(stat.get("shutouts")),
        "sv": _i(stat.get("saves")),
        "hld": _i(stat.get("holds")),
        "ip_outs": ip_to_outs(stat.get("inningsPitched")),
        "h": _i(stat.get("hits")),
        "r": _i(stat.get("runs")),
        "er": _i(stat.get("earnedRuns")),
        "hr": _i(stat.get("homeRuns")),
        "bb": _i(stat.get("baseOnBalls")),
        "so": _i(stat.get("strikeOuts")),
        "hbp": _i(stat.get("hitBatsmen")),
        "bk": _i(stat.get("balks")),
        "wp": _i(stat.get("wildPitches")),
        "bf": _i(stat.get("battersFaced")),
        "extra": None,
        "source": SOURCE,
    }


def inspect_season(year: int, team_id: int = 137) -> None:
    """한 팀의 시즌 스탯 응답 구조 요약만 출력(원본 통째 비로드)."""
    roster = _season_roster(team_id, year)
    print(f"[season {year} team={team_id}] roster fullSeason size={len(roster)}")
    if roster:
        print("  roster[0] keys:", sorted(roster[0].keys()))
    st = _standings(year)
    print(f"  standings teams={len(st)} sample={next(iter(st.items())) if st else None}")
    # 한 선수 hitting split 구조
    if roster:
        mid = roster[0]["person"]["id"]
        sp = _player_season(mid, year, "hitting")
        print(f"  player {mid} hitting splits={len(sp)}")
        if sp:
            print("    split keys:", sorted(sp[0].keys()))
            print("    team:", sp[0].get("team"))
            print("    stat sample keys:", sorted(sp[0]["stat"].keys())[:15])


def backfill_season(year: int, db_path: str | None = None) -> None:
    """StatsAPI 시즌(season) 스탯을 코어 스키마에 멱등 upsert(T1).

    적재 순서:
      season(MLB,year) → 30팀 team_season(standings W/L/T) →
      팀별 fullSeason 로스터로 등장 mlbam 수집 → _link_persons(register 우선) →
      선수별 season hitting/pitching split(팀별) → stint → batting/pitching_season.

    트레이드 선수는 people/{id}/stats split 이 팀별로 분할되어 오므로 split.team.id
    로 team_season 을 잡아 stint 를 팀별로 만든다(멀티 stint 자연 처리).
    """
    from backend.ingest.load.loader import connect, upsert

    conn = connect(str(db_path or DEFAULT_DB))
    cur = conn.cursor()

    # ---- 1) season ----
    upsert(
        conn, "season", [{"league": "MLB", "year": int(year)}],
        conflict_cols=["league", "year"],
    )
    season_id = cur.execute(
        "SELECT id FROM season WHERE league='MLB' AND year=?", (int(year),)
    ).fetchone()["id"]

    # ---- 2) team_season (30팀, standings W/L/T) ----
    standings = _standings(year)
    team_names = _teams_meta(year)
    ts_by_teamid: dict[int, int] = {}
    n_ts = 0
    for team_id, code in TEAMID_TO_CODE.items():
        fr = cur.execute(
            "SELECT id FROM franchise WHERE league='MLB' AND code=?", (code,)
        ).fetchone()
        if not fr:
            print(f"  [team {team_id}->{code}] franchise 미존재 — 건너뜀")
            continue
        rec = standings.get(team_id, {})
        # team_name NOT NULL: teams 메타 풀네임, 없으면 code 폴백
        tname = team_names.get(team_id) or code
        upsert(
            conn, "team_season",
            [{
                "franchise_id": fr["id"],
                "season_id": season_id,
                "org_id": None,
                "park_id": None,
                "team_name": tname,
                "city": None,
                "wins": rec.get("wins"),
                "losses": rec.get("losses"),
                "ties": rec.get("ties") or 0,
                "source": SOURCE,
            }],
            conflict_cols=["franchise_id", "season_id"],
            update_cols=["team_name", "wins", "losses", "ties", "source"],
        )
        ts_id = cur.execute(
            "SELECT id FROM team_season WHERE franchise_id=? AND season_id=?",
            (fr["id"], season_id),
        ).fetchone()["id"]
        ts_by_teamid[team_id] = ts_id
        n_ts += 1
    conn.commit()
    print(f"[season {year}] team_season upsert={n_ts}")

    # ---- 3) 로스터로 등장 mlbam 수집 → person 연결 ----
    mlbam_ids: set[int] = set()
    for team_id in TEAMID_TO_CODE:
        for r in _season_roster(team_id, year):
            pid = (r.get("person") or {}).get("id")
            if pid is not None:
                mlbam_ids.add(int(pid))
    print(f"[season {year}] roster 합집합 mlbam={len(mlbam_ids)}")
    person_map = _link_persons(conn, sorted(mlbam_ids), year)

    # ---- 4) 선수별 season split → stint + batting/pitching_season ----
    def stint_id_for(person_id: int, ts_id: int) -> int:
        row = cur.execute(
            "SELECT id FROM stint WHERE person_id=? AND team_season_id=? "
            "AND order_in_season=1",
            (person_id, ts_id),
        ).fetchone()
        if row:
            return row["id"]
        cur.execute(
            "INSERT INTO stint (person_id, team_season_id, order_in_season) "
            "VALUES (?,?,1)",
            (person_id, ts_id),
        )
        return cur.lastrowid

    bat_rows: list[dict] = []
    pit_rows: list[dict] = []
    seen_bat: set[int] = set()
    seen_pit: set[int] = set()
    n_players = 0

    for mid in sorted(mlbam_ids):
        person_id = person_map.get(mid)
        if person_id is None:
            continue
        n_players += 1
        for group, builder, rows, seen in (
            ("hitting", _bat_row, bat_rows, seen_bat),
            ("pitching", _pit_row, pit_rows, seen_pit),
        ):
            for sp in _player_season(mid, year, group):
                team = sp.get("team") or {}
                team_id = team.get("id")
                if team_id is None:
                    continue
                ts_id = ts_by_teamid.get(int(team_id))
                if ts_id is None:
                    # sportId=1 외(마이너) 팀 split 은 건너뜀
                    continue
                stat = sp.get("stat") or {}
                stint_id = stint_id_for(person_id, ts_id)
                if stint_id in seen:
                    continue
                seen.add(stint_id)
                rows.append(builder(stat, stint_id))
    conn.commit()

    upsert(conn, "batting_season", bat_rows, conflict_cols=["stint_id"])
    upsert(conn, "pitching_season", pit_rows, conflict_cols=["stint_id"])
    conn.commit()

    def n(q, *a):
        return cur.execute(q, a).fetchone()[0]

    print(f"[backfill_season {year}] done (source={SOURCE})")
    print("  season_id      :", season_id)
    print("  team_season    :", n("SELECT count(*) FROM team_season WHERE season_id=?", season_id))
    print("  players linked :", n_players)
    print("  batting_season :", len(bat_rows))
    print("  pitching_season:", len(pit_rows))
    print("  stint(season)  :", n(
        "SELECT count(*) FROM stint st JOIN team_season ts ON ts.id=st.team_season_id "
        "WHERE ts.season_id=?", season_id,
    ))
    conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(prog="mlb_statsapi")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ins = sub.add_parser("inspect", help="schedule+boxscore 구조 요약")
    p_ins.add_argument("date", help="YYYY-MM-DD")

    p_bf = sub.add_parser("backfill", help="Final 정규시즌 경기 적재")
    p_bf.add_argument("--start", required=True)
    p_bf.add_argument("--end", required=True)
    p_bf.add_argument("--db", default=None)

    p_is = sub.add_parser("inspect-season", help="시즌 스탯 응답 구조 요약")
    p_is.add_argument("--year", type=int, required=True)
    p_is.add_argument("--team", type=int, default=137)

    p_bs = sub.add_parser("backfill-season", help="시즌(season) 스탯 적재(T1)")
    p_bs.add_argument("--year", type=int, required=True)
    p_bs.add_argument("--db", default=None)

    args = ap.parse_args()
    if args.cmd == "inspect":
        inspect(args.date)
    elif args.cmd == "backfill":
        backfill(args.start, args.end, db_path=args.db)
    elif args.cmd == "inspect-season":
        inspect_season(args.year, args.team)
    elif args.cmd == "backfill-season":
        backfill_season(args.year, db_path=args.db)


if __name__ == "__main__":
    main()
