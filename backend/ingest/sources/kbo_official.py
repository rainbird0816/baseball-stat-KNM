"""KBO 수집기 (Phase 3) — KBO 공식 기록실(koreabaseball.com) 크롤링/적재.

robots.txt 에서 `/Record/` 는 허용(Disallow 는 /Common /Help /Member /ws 뿐).
정중한 크롤만: 요청 간 폴리트 딜레이(>=1.5s), User-Agent 명시, 원본 HTML 은
data/raw/kbo/<year>/ 에 캐시 후 재파싱(재요청 최소화).

ASP.NET viewstate POST: 페이지 기본 렌더는 현재(진행중) 시즌이라, 완료 시즌
데이터를 받으려면 __VIEWSTATE/__VIEWSTATEGENERATOR/__EVENTVALIDATION 등
hidden 필드를 GET 으로 확보한 뒤 ddlSeason/ddlSeries/ddlTeam 을 세팅하고
__EVENTTARGET=ddlTeam(또는 ddlSeason) 으로 POST 한다.

원본 HTML 을 컨텍스트/프롬프트에 통째로 넣지 않는다 — inspect() 는 표
컬럼/행수/샘플 1행 요약만 출력한다.

적재(FK 순서):
  season → team_season(순위 W-L-T) → person(+external_id, playerId) →
  stint → batting_season / pitching_season.  모두 멱등 upsert.

선수명: name_native=한글, name_roman=NULL(사이트 한글 전용 → Phase 5 보강).
person 식별: 선수명 셀 상세링크의 playerId → ('kbo', playerId) external_id.

사용:
  python -m backend.ingest.sources.kbo_official inspect 2024 hitter1 HT
  python -m backend.ingest.sources.kbo_official backfill --year 2024
"""
from __future__ import annotations

import argparse
import io
import math
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw" / "kbo"
SOURCE = "kbo"
DEFAULT_DB = ROOT / "data" / "baseball.db"

BASE = "https://www.koreabaseball.com"

# page 키 -> (URL 경로, 캐시 파일 prefix)
PAGE_URLS = {
    "hitter1":  "/Record/Player/HitterBasic/Basic1.aspx",
    "hitter2":  "/Record/Player/HitterBasic/Basic2.aspx",
    "pitcher1": "/Record/Player/PitcherBasic/Basic1.aspx",
    "teamrank": "/Record/TeamRank/TeamRank.aspx",
}
HITTER_PAGES = ("hitter1", "hitter2")

# KBO 사이트 ddlTeam 코드 → franchise.code (RECON 표)
SITE_TEAM_TO_CODE = {
    "LG": "LG", "KT": "KT", "SS": "SS", "HT": "KIA", "HH": "HH",
    "OB": "OB", "NC": "NC", "SK": "SK", "LT": "LT", "WO": "WO",
}
# 적재 루프에서 도는 사이트 팀코드 순서
SITE_TEAMS = ["LG", "KT", "SS", "HT", "HH", "OB", "NC", "SK", "LT", "WO"]

# 순위표 팀명 라벨(사이트 ddlTeam 라벨/표 표기) → franchise.code
# 과거 시즌 라벨도 포함: SSG→SK 계보(SK 와이번스), 키움→WO 계보(넥센/우리/히어로즈).
RANK_LABEL_TO_CODE = {
    "LG": "LG", "KT": "KT", "삼성": "SS", "KIA": "KIA", "한화": "HH",
    "두산": "OB", "NC": "NC", "SSG": "SK", "롯데": "LT", "키움": "WO",
    "SK": "SK", "넥센": "WO", "우리": "WO", "히어로즈": "WO",
}

ORG_ID = 30  # KBO organization (서브리그 없음)
SERIES_REGULAR = 0  # ddlSeries 0 = KBO 정규시즌

_UA = "baseball-archive ingest (rainbird0816@gmail.com; +koreabaseball.com polite crawl)"
_DELAY = 1.6  # 요청 간 폴리트 딜레이(초)

# 타격 표(Basic1, 16열) 컬럼 인덱스 (헤더 기준 0-base)
# 순위,선수명,팀명,AVG,G,PA,AB,R,H,2B,3B,HR,TB,RBI,SAC,SF
BAT1_COL = {
    "g": 4, "pa": 5, "ab": 6, "r": 7, "h": 8, "b2": 9, "b3": 10,
    "hr": 11, "rbi": 13, "sh": 14, "sf": 15,
}
# 타격 표(Basic2, 15열): 순위,선수명,팀명,AVG,BB,IBB,HBP,SO,GDP,SLG,OBP,OPS,MH,RISP,PH-BA
BAT2_COL = {"bb": 4, "ibb": 5, "hbp": 6, "so": 7, "gidp": 8}
# 투수 표(Basic1, 19열): 순위,선수명,팀명,ERA,G,W,L,SV,HLD,WPCT,IP,H,HR,BB,HBP,SO,R,ER,WHIP
PIT1_COL = {
    "g": 4, "w": 5, "l": 6, "sv": 7, "hld": 8, "ip": 10, "h": 11,
    "hr": 12, "bb": 13, "hbp": 14, "so": 15, "r": 16, "er": 17,
}
# 순위표(12열): 순위,팀명,경기,승,패,무,승률,...
RANK_COL = {"team": 1, "games": 2, "w": 3, "l": 4, "t": 5}


# --------------------------------------------------------------------------- #
# 값 정규화
# --------------------------------------------------------------------------- #
def _i(v):
    """결측/NaN/빈칸/'-' → None, 그 외 파이썬 int."""
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


def ip_to_outs(ip) -> int | None:
    """KBO IP 표기 → 아웃 정수. '75 1/3'→226, '75 2/3'→227, '75'→225."""
    if ip is None:
        return None
    try:
        if isinstance(ip, float) and math.isnan(ip):
            return None
    except TypeError:
        pass
    s = str(ip).strip()
    if s in ("", "nan", "-", "－"):
        return None
    parts = s.split()
    try:
        whole = int(parts[0])
    except (ValueError, IndexError):
        return None
    add = 0
    if len(parts) > 1:
        frac = parts[1]
        if frac == "1/3":
            add = 1
        elif frac == "2/3":
            add = 2
    return whole * 3 + add


def _name(v):
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "nan"):
        return None
    return s


# --------------------------------------------------------------------------- #
# 폼/네트워크 (ASP.NET viewstate POST)
# --------------------------------------------------------------------------- #
def _cache_path(year: int, page: str, team: str | None) -> Path:
    tag = team if team else "all"
    return RAW / str(year) / f"{page}_{tag}.html"


def _hidden_fields(html: str) -> dict[str, str]:
    """페이지의 모든 hidden input(name→value) 을 추출(viewstate 포함)."""
    fields: dict[str, str] = {}
    for m in re.finditer(
        r'<input[^>]*type="hidden"[^>]*>', html, re.IGNORECASE
    ):
        tag = m.group(0)
        nm = re.search(r'name="([^"]*)"', tag)
        if not nm:
            continue
        val = re.search(r'value="([^"]*)"', tag)
        fields[nm.group(1)] = val.group(1) if val else ""
    return fields


def _select_name(html: str, suffix: str) -> str | None:
    """suffix(예 'ddlTeam') 로 끝나는 <select> name 전체를 찾는다."""
    for m in re.finditer(r'<select[^>]*name="([^"]+)"', html):
        nm = m.group(1)
        if nm.endswith(suffix) or ("$" + suffix + "$") in nm or nm.endswith("$" + suffix):
            return nm
    return None


def _pager_target(html: str) -> str | None:
    """현재 페이지(class='on')보다 큰 다음 페이지 번호 버튼의 postback 타깃 반환.

    pager 는 ucPager$btnNoN. 현재 페이지는 btnNoN class='on'. 다음 번호가
    있으면 그 EVENTTARGET(ctl00$...$ucPager$btnNoN) 을 반환, 없으면 None.
    """
    m = re.search(r'<div class="paging">(.*?)</div>', html, re.S)
    if not m:
        return None
    pg = m.group(1)
    cur_m = re.search(r'btnNo(\d+)"\s+class="on"', pg)
    cur = int(cur_m.group(1)) if cur_m else 1
    # btnNoN → 전체 postback 타깃 추출
    targets: dict[int, str] = {}
    for a in re.finditer(
        r"__doPostBack\(&#39;([^&]*ucPager\$btnNo(\d+))&#39;", pg
    ):
        targets[int(a.group(2))] = a.group(1)
    nxts = [no for no in targets if no > cur]
    if not nxts:
        return None
    return targets[min(nxts)]


def fetch_form(page: str, *, year: int, team_code: str | None = None,
               series: int = SERIES_REGULAR, force: bool = False) -> list[str]:
    """ASP.NET viewstate POST 로 한 페이지(+모든 페이지네이션)를 받아 캐시.

    플레이어 페이지(hitter/pitcher)는 ASP.NET 캐스케이드라 2단계 POST 가
    필요하다: ① ddlSeason 변경 POST → ② 새 viewstate 로 ddlTeam 필터 POST.
    (단일 POST 로 ddlTeam 을 같이 보내면 팀 필터가 무시되고 리그 전체가 온다.)
    팀당 30행 초과 시 ucPager 로 페이지네이션 → 모든 페이지 수집.

    반환: 페이지별 HTML 문자열 리스트(teamrank 는 1개). 각 페이지를
    data/raw/kbo/<year>/<page>_<team>[_pN].html 에 캐시.
    """
    import requests

    base_cache = _cache_path(year, page, team_code)
    # 캐시 히트: 첫 페이지 + 연속한 _p2,_p3... 모두 읽기
    if base_cache.exists() and base_cache.stat().st_size > 1000 and not force:
        pages = [base_cache.read_bytes().decode("utf-8", "replace")]
        i = 2
        while True:
            extra = base_cache.with_name(
                base_cache.stem + f"_p{i}" + base_cache.suffix)
            if extra.exists() and extra.stat().st_size > 1000:
                pages.append(extra.read_bytes().decode("utf-8", "replace"))
                i += 1
            else:
                break
        return pages
    base_cache.parent.mkdir(parents=True, exist_ok=True)

    url = BASE + PAGE_URLS[page]

    def _post(sess, html, target, overrides):
        data = _hidden_fields(html)
        data.update(overrides)
        data["__EVENTTARGET"] = target or ""
        data["__EVENTARGUMENT"] = ""
        r = sess.post(url, data=data, timeout=30)
        r.raise_for_status()
        time.sleep(_DELAY)
        return r.content.decode("utf-8", "replace")

    last_err: Exception | None = None
    for attempt in range(4):
        try:
            sess = requests.Session()
            sess.headers.update({"User-Agent": _UA})

            g = sess.get(url, timeout=30)
            g.raise_for_status()
            time.sleep(_DELAY)
            html = g.content.decode("utf-8", "replace")

            if page == "teamrank":
                yr = _select_name(html, "ddlYear")
                sr = _select_name(html, "ddlSeries")
                ov = {}
                if yr:
                    ov[yr] = str(year)
                if sr:
                    ov[sr] = str(series)
                html = _post(sess, html, yr, ov)
                base_cache.write_bytes(html.encode("utf-8"))
                return [html]

            # ---- 플레이어 페이지 ----
            season = _select_name(html, "ddlSeason")
            tm = _select_name(html, "ddlTeam")
            keep = {}  # 매 POST 마다 유지할 ddl 값
            if season:
                keep[season] = str(year)
                html = _post(sess, html, season, {season: str(year)})
            if tm and team_code:
                keep[tm] = team_code
                html = _post(sess, html, tm, dict(keep))

            pages = [html]
            base_cache.write_bytes(html.encode("utf-8"))
            # 페이지네이션: 다음 번호 버튼이 있으면 계속 POST
            guard = 0
            while guard < 20:
                guard += 1
                nxt = _pager_target(html)
                if not nxt:
                    break
                html = _post(sess, html, nxt, dict(keep))
                idx = len(pages) + 1
                extra = base_cache.with_name(
                    base_cache.stem + f"_p{idx}" + base_cache.suffix)
                extra.write_bytes(html.encode("utf-8"))
                pages.append(html)
            return pages
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(3)
    raise SystemExit(
        f"네트워크 실패: {url} team={team_code} "
        f"({type(last_err).__name__}: {last_err})"
    )


# --------------------------------------------------------------------------- #
# 파싱
# --------------------------------------------------------------------------- #
def _stat_table(html: str):
    """선수 기록 표(가장 컬럼 많은 표)를 DataFrame 으로 반환, 없으면 None.

    과거 시즌(예 2010)엔 KT/NC 등 미창단 팀이 없어 해당 팀 페이지가 표 없는
    빈/오류 페이지로 돌아온다. 그 경우 예외 대신 None 을 반환해 건너뛴다.
    """
    import pandas as pd

    try:
        tabs = pd.read_html(io.StringIO(html))
    except ValueError:
        return None
    best = None
    for t in tabs:
        if t.shape[1] >= 12 and (best is None or t.shape[1] > best.shape[1]):
            # 첫 컬럼이 순위(헤더 '순위')인 표 우선
            if "순위" in [str(c) for c in t.columns]:
                best = t
    if best is None:
        for t in tabs:
            if t.shape[1] >= 12 and (best is None or t.shape[1] > best.shape[1]):
                best = t
    return best


def _player_ids(html: str) -> list[str]:
    """기록 표 tbody 의 선수 상세링크 playerId 를 행 순서대로 추출."""
    # 기록 표는 class 에 tData 를 쓰는 표 안에 있음. tbody 우선.
    m = re.search(r'<tbody[^>]*>(.*?)</tbody>', html, re.S)
    scope = m.group(1) if m else html
    return re.findall(r'playerId=(\d+)', scope)


def parse_player_rows(pages: list[str]) -> list[tuple[str, list]]:
    """플레이어 페이지(여러 페이지) → [(playerId, row_cells), ...] (중복 제거).

    각 페이지의 기록표 데이터행과 playerId 를 행 순서대로 zip. 페이지네이션으로
    같은 선수가 중복될 일은 없지만 playerId 기준으로 dedup 한다.
    """
    out: dict[str, tuple[str, list]] = {}
    for html in pages:
        t = _stat_table(html)
        ids = _player_ids(html)
        if t is None:
            continue
        for ri in range(min(t.shape[0], len(ids))):
            pid = ids[ri]
            cells = [t.iloc[ri, c] for c in range(t.shape[1])]
            out[pid] = (pid, cells)
    return list(out.values())


# --------------------------------------------------------------------------- #
# inspect
# --------------------------------------------------------------------------- #
def inspect(year: int, page: str, team: str | None = None) -> None:
    """한 페이지 표 구조 요약만 출력(원본 통째 출력 금지)."""
    import pandas as pd

    if page not in PAGE_URLS:
        raise SystemExit(f"page 는 {list(PAGE_URLS)} 중 하나여야 함 (받음: {page})")
    pages = fetch_form(page, year=year, team_code=team)
    html = pages[0]
    tabs = pd.read_html(io.StringIO(html))
    print(f"[kbo {year}/{page} team={team}] num_pages={len(pages)} "
          f"num_tables(p1)={len(tabs)}")
    for i, t in enumerate(tabs):
        cols = [str(c) for c in t.columns.tolist()]
        print(f"  table[{i}] shape={t.shape} cols={cols[:20]}")
    t = _stat_table(html)
    if t is not None:
        print(f"  -> 기록표(p1) shape={t.shape}")
        if t.shape[0]:
            print(f"  -> sample[0]: {[str(x) for x in t.iloc[0].tolist()]}")
        if page != "teamrank":
            rows = parse_player_rows(pages)
            print(f"  -> playerId(전 페이지 합·dedup)={len(rows)} sample={[r[0] for r in rows[:3]]}")
        if page == "pitcher1" and t.shape[0]:
            ip = t.iloc[0, PIT1_COL["ip"]]
            print(f"  -> IP 표기 예: {ip!r} -> ip_outs={ip_to_outs(ip)}")


# --------------------------------------------------------------------------- #
# backfill
# --------------------------------------------------------------------------- #
def backfill(year: int, db_path: str | None = None) -> None:
    """그 시즌(정규) 10팀 타자/투수 + 순위표를 코어 스키마에 멱등 적재."""
    from backend.ingest.load.loader import connect, upsert

    conn = connect(str(db_path or DEFAULT_DB))
    cur = conn.cursor()

    # ---- 1) season ----
    upsert(conn, "season", [{"league": "KBO", "year": int(year)}],
           conflict_cols=["league", "year"])
    season_id = cur.execute(
        "SELECT id FROM season WHERE league='KBO' AND year=?", (int(year),)
    ).fetchone()["id"]

    # ---- franchise.id lookup (기존 시드 사용, 새로 만들지 않음) ----
    fr_id_by_code: dict[str, int] = {}
    for code in set(SITE_TEAM_TO_CODE.values()):
        row = cur.execute(
            "SELECT id FROM franchise WHERE league='KBO' AND code=?", (code,)
        ).fetchone()
        if row is None:
            raise SystemExit(f"franchise 누락: KBO {code} (시드 005 확인)")
        fr_id_by_code[code] = row["id"]

    # ---- 2) team_season (순위표 W-L-T) ----
    rank_pages = fetch_form("teamrank", year=year, series=SERIES_REGULAR)
    rt = _stat_table(rank_pages[0])
    ts_id_by_code: dict[str, int] = {}
    rank_check: list[tuple] = []
    if rt is not None:
        for ri in range(rt.shape[0]):
            label = str(rt.iloc[ri, RANK_COL["team"]]).strip()
            code = RANK_LABEL_TO_CODE.get(label)
            if code is None:
                continue
            fr_id = fr_id_by_code[code]
            wins = _i(rt.iloc[ri, RANK_COL["w"]])
            losses = _i(rt.iloc[ri, RANK_COL["l"]])
            ties = _i(rt.iloc[ri, RANK_COL["t"]]) or 0
            games = _i(rt.iloc[ri, RANK_COL["games"]])
            upsert(conn, "team_season", [{
                "franchise_id": fr_id, "season_id": season_id,
                "org_id": ORG_ID, "park_id": None,
                "team_name": label, "city": None,
                "wins": wins, "losses": losses, "ties": ties,
                "source": SOURCE,
            }], conflict_cols=["franchise_id", "season_id"])
            ts_id_by_code[code] = cur.execute(
                "SELECT id FROM team_season WHERE franchise_id=? AND season_id=?",
                (fr_id, season_id),
            ).fetchone()["id"]
            rank_check.append((code, label, wins, losses, ties, games))
    conn.commit()

    # ---- person + stint lookup-or-insert 헬퍼 (playerId 기준 멱등) ----
    def person_stint_for(player_id: str, name_native: str, code: str) -> int | None:
        ts_id = ts_id_by_code.get(code)
        if ts_id is None or not player_id or not name_native:
            return None
        ext = cur.execute(
            "SELECT person_id FROM person_external_id WHERE source=? AND external_id=?",
            (SOURCE, player_id),
        ).fetchone()
        if ext:
            person_id = ext["person_id"]
        else:
            cur.execute(
                "INSERT INTO person (name_native, name_roman) VALUES (?, ?)",
                (name_native, None),  # 사이트 한글 전용 → 로마자 NULL
            )
            person_id = cur.lastrowid
            upsert(conn, "person_external_id",
                   [{"person_id": person_id, "source": SOURCE, "external_id": player_id}],
                   conflict_cols=["source", "external_id"], update_cols=["person_id"])
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

    # ---- 3) 타자: 팀별 Basic1 + Basic2 머지(playerId 기준) ----
    pages_seen = 0
    bat_rows: dict[int, dict] = {}  # stint_id -> row
    for site in SITE_TEAMS:
        code = SITE_TEAM_TO_CODE[site]
        h1_pages = fetch_form("hitter1", year=year, team_code=site,
                              series=SERIES_REGULAR)
        h2_pages = fetch_form("hitter2", year=year, team_code=site,
                              series=SERIES_REGULAR)
        pages_seen += len(h1_pages) + len(h2_pages)
        r1_rows = parse_player_rows(h1_pages)        # [(pid, cells)]
        b2_by_pid = {pid: cells for pid, cells in parse_player_rows(h2_pages)}

        for pid, r1 in r1_rows:
            name = _name(r1[1])
            sid = person_stint_for(pid, name, code)
            if sid is None:
                continue
            r2 = b2_by_pid.get(pid)
            row = {
                "stint_id": sid,
                "g": _i(r1[BAT1_COL["g"]]), "pa": _i(r1[BAT1_COL["pa"]]),
                "ab": _i(r1[BAT1_COL["ab"]]), "r": _i(r1[BAT1_COL["r"]]),
                "h": _i(r1[BAT1_COL["h"]]), "b2": _i(r1[BAT1_COL["b2"]]),
                "b3": _i(r1[BAT1_COL["b3"]]), "hr": _i(r1[BAT1_COL["hr"]]),
                "rbi": _i(r1[BAT1_COL["rbi"]]),
                "sb": None, "cs": None,  # 결손(RunningBasic 필요) → NULL
                "bb": _i(r2[BAT2_COL["bb"]]) if r2 else None,
                "so": _i(r2[BAT2_COL["so"]]) if r2 else None,
                "ibb": _i(r2[BAT2_COL["ibb"]]) if r2 else None,
                "hbp": _i(r2[BAT2_COL["hbp"]]) if r2 else None,
                "sh": _i(r1[BAT1_COL["sh"]]), "sf": _i(r1[BAT1_COL["sf"]]),
                "gidp": _i(r2[BAT2_COL["gidp"]]) if r2 else None,
                "extra": None, "source": SOURCE,
            }
            bat_rows[sid] = row

    bat_n = upsert(conn, "batting_season", list(bat_rows.values()),
                   conflict_cols=["stint_id"])
    conn.commit()

    # ---- 4) 투수: 팀별 Basic1 ----
    pit_rows: dict[int, dict] = {}
    for site in SITE_TEAMS:
        code = SITE_TEAM_TO_CODE[site]
        p1_pages = fetch_form("pitcher1", year=year, team_code=site,
                              series=SERIES_REGULAR)
        pages_seen += len(p1_pages)
        for pid, r in parse_player_rows(p1_pages):
            name = _name(r[1])
            sid = person_stint_for(pid, name, code)
            if sid is None:
                continue
            pit_rows[sid] = {
                "stint_id": sid,
                "w": _i(r[PIT1_COL["w"]]), "l": _i(r[PIT1_COL["l"]]),
                "g": _i(r[PIT1_COL["g"]]), "gs": None, "cg": None, "sho": None,
                "sv": _i(r[PIT1_COL["sv"]]), "hld": _i(r[PIT1_COL["hld"]]),
                "ip_outs": ip_to_outs(r[PIT1_COL["ip"]]),
                "h": _i(r[PIT1_COL["h"]]), "r": _i(r[PIT1_COL["r"]]),
                "er": _i(r[PIT1_COL["er"]]), "hr": _i(r[PIT1_COL["hr"]]),
                "bb": _i(r[PIT1_COL["bb"]]), "so": _i(r[PIT1_COL["so"]]),
                "hbp": _i(r[PIT1_COL["hbp"]]),
                "bk": None, "wp": None, "bf": None,  # Basic1 결손 → NULL
                "extra": None, "source": SOURCE,
            }
    pit_n = upsert(conn, "pitching_season", list(pit_rows.values()),
                   conflict_cols=["stint_id"])
    conn.commit()

    # ---- 요약 ----
    def n(q, *a):
        return cur.execute(q, a).fetchone()[0]

    print(f"backfill year={year} done (source={SOURCE})")
    print("  pages fetched  :", pages_seen, "(타자 20 + 투수 10 + 순위 1)")
    print("  season_id      :", season_id)
    print("  team_season    :", n(
        "SELECT count(*) FROM team_season WHERE season_id=? AND source='kbo'", season_id))
    print("  person(kbo ext):", n(
        "SELECT count(DISTINCT person_id) FROM person_external_id WHERE source='kbo'"))
    print("  stint(kbo ts)  :", n(
        "SELECT count(*) FROM stint s JOIN team_season ts ON s.team_season_id=ts.id "
        "WHERE ts.season_id=? AND ts.source='kbo'", season_id))
    print("  batting_season :", bat_n, "/ total kbo",
          n("SELECT count(*) FROM batting_season WHERE source='kbo'"))
    print("  pitching_season:", pit_n, "/ total kbo",
          n("SELECT count(*) FROM pitching_season WHERE source='kbo'"))
    # 순위 정합(경기 = 승+패+무)
    print("  순위 정합 (code label W-L-T games | W+L+T):")
    for code, label, w, l, t, g in rank_check:
        tot = (w or 0) + (l or 0) + (t or 0)
        flag = "OK" if g == tot else "MISMATCH"
        print(f"    {code:4} {label:5} {w}-{l}-{t} games={g} sum={tot} [{flag}]")
    conn.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(prog="kbo_official")
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("inspect")
    pi.add_argument("year", type=int)
    pi.add_argument("page", choices=list(PAGE_URLS))
    pi.add_argument("team", nargs="?", default=None,
                    help="사이트 ddlTeam 코드(예 HT). 생략 시 전체.")
    pb = sub.add_parser("backfill")
    pb.add_argument("--year", type=int, required=True)
    pb.add_argument("--db")
    a = p.parse_args()
    if a.cmd == "inspect":
        inspect(a.year, a.page, a.team)
    else:
        backfill(a.year, db_path=a.db)
