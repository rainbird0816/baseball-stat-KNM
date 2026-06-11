# PROJECT_BRIEF — baseball-archive

KBO · NPB · MLB 세 리그의 팀/타자/투수 데이터를 하나의 통합 DB로 수집·정규화하는 프로젝트.
시즌 누적 스탯부터 경기 단위 박스스코어, 팀 역대 역사까지 담는다.

> 이 문서는 Claude CLI 세션의 단일 진실 소스(single source of truth)다.
> 작업을 시작하기 전에 항상 이 문서를 먼저 읽고, 구조를 바꿀 때는 이 문서를 먼저 갱신한다.

---

## 1. 목표와 범위

### 목표
- 세 리그를 **하나의 통합 스키마**로 합쳐, 한 선수의 리그 간 커리어(예: 오타니 NPB→MLB, 이정후 KBO→MLB)와
  한 프랜차이즈의 역대 역사(예: 해태→KIA)를 끊김 없이 조회한다.
- 팀 데이터, 타자 데이터, 투수 데이터의 **누적·시즌 스탯**을 기본으로 하고, **경기 단위**까지 확보한다.

### 범위에 포함
- 차원: 리그/지구 계층, 프랜차이즈, 시즌, 구장, 인물, 외부 ID 매핑, **리그별 규칙(league_rule)**
- 팩트(시즌): 타격 / 투구 / 수비 시즌 스탯
- 팩트(경기): 경기 결과, 선수별 경기 타격/투구 라인(박스스코어)
- 보조: **우승 시리즈(월드시리즈·일본시리즈·한국시리즈)**, 수상 내역, 순위표, **구단 로고 변천사**

### 범위에서 제외
- **투구 단위(pitch-by-pitch) / 이벤트 단위 데이터 → 범위 제외.** 시즌·경기 단위까지만 다룬다.
- 마이너리그·아마추어·국제대회 → 1차 범위 밖
- 실시간 중계(라이브 인플레이) → 범위 밖. "당일 증분"은 **종료된 경기**만 대상으로 한다.

---

## 2. 핵심 설계 원칙

1. **통합 코어 + 리그별 확장** — 모든 리그·시대 공통 스탯은 정식 컬럼, 희소/리그 특화 지표(OPS+, wRC+ 등)는 `extra` JSON 컬럼.
2. **저장은 통합, 표현·규칙은 리그 분리** — DB는 한 벌이라 크로스리그 커리어가 가능하되, 리그마다 다른 규칙(DH 도입 시점, 무승부, 포스트시즌 형식, 팀 수)은 `league_rule`에 명시하고, **프론트엔드는 리그별 페이지로 분리**한다. 공통 규칙과 리그 고유 규칙이 공존하므로 이 분리는 필수.
3. **프랜차이즈 연속성** — `franchise`(불변 정체성) ↔ `team_season`(시점별 이름·연고)을 분리. 구단명 변경·연고 이전·리그 개편을 team_season이 흡수. 로고도 프랜차이즈에 시점별로 매단다.
4. **크로스리그 인물 동일성** — `person`은 리그 무관 1인 1행. `person_external_id`로 소스별 ID를 묶는다. **이 매칭이 가장 손이 많이 가는 작업.**
5. **이닝은 아웃 정수(`ip_outs`)로 저장** — 6.1/6.2 표기를 그대로 넣으면 합산 시 반드시 버그. 출력할 때만 `outs//3`, `outs%3` 변환.
6. **무승부 컬럼(`ties`) 필수** — NPB는 무승부가 흔하다. 순위는 W-L-T.
7. **이름 원어+로마자 병기** — `name_native`(송병화/大谷翔平) + `name_roman`(Song Byeong-hwa/Ohtani).
8. **provenance(`source`) 컬럼** — 각 숫자의 출처(KBO공식/Statiz/Lahman 등)를 남겨 소스 간 불일치를 조정.
9. **원본 파일은 모델 컨텍스트에 절대 로드 금지** — CSV/shapefile 원본은 `df.head()`, `df.columns`, 행 수 요약만 넘긴다. 전체 파일을 프롬프트에 붙이지 않는다.

---

## 3. 데이터 입도(Granularity) 정책

| 티어 | 내용 | MLB | NPB | KBO | 대략 볼륨 | 저장 |
|---|---|---|---|---|---|---|
| T1 (필수) | 시즌 누적 스탯 | 1871~ | 1936~ | 1982~ | 수십만 행 | SQLite |
| T2 (권장) | 경기 단위 박스스코어 | ◎ | ○ | ○ | 수백만 행 | SQLite |

- **최종 목표는 T2(경기 단위)까지.** 투구·이벤트 단위는 다루지 않는다.
- 깊이는 리그마다 다른 것을 받아들인다. 스키마는 경기 단위까지 허용하되 데이터 희소함(과거 박스스코어 결손 등)은 자연스럽게 둔다.

---

## 4. 데이터 모델 (코어 DDL)

> 아래는 시작점. CLI가 이를 기반으로 마이그레이션 파일을 생성하고 확장한다.
> SQLite 기준. JSON1 확장(`json_extract`)을 전제로 한다.

```sql
-- ===== 차원(Dimension) =====
CREATE TABLE organization (         -- 자기참조 리그 계층
  id          INTEGER PRIMARY KEY,
  parent_id   INTEGER REFERENCES organization(id),
  level       TEXT NOT NULL,        -- 'org' | 'subleague' | 'division'
  name        TEXT NOT NULL,        -- 'MLB','American League','AL East','KBO','NPB','Central'
  short_code  TEXT
);

CREATE TABLE franchise (
  id           INTEGER PRIMARY KEY,
  league       TEXT NOT NULL,       -- 'MLB' | 'KBO' | 'NPB'
  code         TEXT NOT NULL,       -- 안정 식별자 (예: 'TIG')
  lineage      TEXT,                -- '해태→KIA'
  founded_year INTEGER
);

CREATE TABLE season (
  id      INTEGER PRIMARY KEY,
  league  TEXT NOT NULL,
  year    INTEGER NOT NULL,
  UNIQUE(league, year)
);

CREATE TABLE park (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  city        TEXT,
  park_factor REAL
);

CREATE TABLE team_season (
  id            INTEGER PRIMARY KEY,
  franchise_id  INTEGER NOT NULL REFERENCES franchise(id),
  season_id     INTEGER NOT NULL REFERENCES season(id),
  org_id        INTEGER REFERENCES organization(id),  -- 그 시즌 소속(지구/리그)
  park_id       INTEGER REFERENCES park(id),
  team_name     TEXT NOT NULL,      -- 그 시즌 명칭 '해태 타이거즈'
  city          TEXT,
  wins          INTEGER,
  losses        INTEGER,
  ties          INTEGER DEFAULT 0,  -- NPB 대응
  source        TEXT,
  UNIQUE(franchise_id, season_id)
);

-- ===== 인물 & 참여 =====
CREATE TABLE person (
  id          INTEGER PRIMARY KEY,
  name_native TEXT,                 -- 원어
  name_roman  TEXT,                 -- 로마자
  birth_date  TEXT,
  bats        TEXT,                 -- 'L'|'R'|'S'
  throws      TEXT,                 -- 'L'|'R'
  debut_date  TEXT
);

CREATE TABLE person_external_id (
  person_id   INTEGER NOT NULL REFERENCES person(id),
  source      TEXT NOT NULL,        -- 'mlbam','bbref','statiz','npb','retrosheet','fangraphs'
  external_id TEXT NOT NULL,
  PRIMARY KEY (source, external_id)
);

CREATE TABLE stint (                -- 시즌 중 트레이드 시 1인 다중 stint
  id              INTEGER PRIMARY KEY,
  person_id       INTEGER NOT NULL REFERENCES person(id),
  team_season_id  INTEGER NOT NULL REFERENCES team_season(id),
  primary_pos     TEXT,
  jersey          TEXT,
  order_in_season INTEGER DEFAULT 1
);

-- ===== 팩트: 시즌 스탯 =====
CREATE TABLE batting_season (
  stint_id INTEGER PRIMARY KEY REFERENCES stint(id),
  g INTEGER, pa INTEGER, ab INTEGER, r INTEGER, h INTEGER,
  b2 INTEGER, b3 INTEGER, hr INTEGER, rbi INTEGER,
  sb INTEGER, cs INTEGER, bb INTEGER, so INTEGER,
  ibb INTEGER, hbp INTEGER, sh INTEGER, sf INTEGER, gidp INTEGER,
  extra JSON,                       -- wRC+, OPS+, wOBA 등 희소·파생 지표
  source TEXT
);

CREATE TABLE pitching_season (
  stint_id INTEGER PRIMARY KEY REFERENCES stint(id),
  w INTEGER, l INTEGER, g INTEGER, gs INTEGER, cg INTEGER, sho INTEGER,
  sv INTEGER, hld INTEGER, ip_outs INTEGER,            -- 이닝은 아웃 정수
  h INTEGER, r INTEGER, er INTEGER, hr INTEGER,
  bb INTEGER, so INTEGER, hbp INTEGER, bk INTEGER, wp INTEGER, bf INTEGER,
  extra JSON,                       -- FIP, ERA+, xFIP 등
  source TEXT
);

CREATE TABLE fielding_season (
  id INTEGER PRIMARY KEY,
  stint_id INTEGER NOT NULL REFERENCES stint(id),
  pos TEXT NOT NULL,
  g INTEGER, gs INTEGER, inn_outs INTEGER,
  po INTEGER, a INTEGER, e INTEGER, dp INTEGER,
  pb INTEGER, sb_c INTEGER, cs_c INTEGER,              -- 포수 한정
  UNIQUE(stint_id, pos)
);

-- ===== 팩트: 경기 단위 (T2) =====
CREATE TABLE game (
  id          INTEGER PRIMARY KEY,
  league      TEXT NOT NULL,
  season_id   INTEGER REFERENCES season(id),
  game_date   TEXT NOT NULL,        -- 'YYYY-MM-DD'
  game_type   TEXT,                 -- 'regular'|'postseason'|'exhibition'
  home_ts_id  INTEGER REFERENCES team_season(id),
  away_ts_id  INTEGER REFERENCES team_season(id),
  park_id     INTEGER REFERENCES park(id),
  home_score  INTEGER, away_score INTEGER,
  innings     INTEGER,
  status      TEXT,                 -- 'final'|'tie'|'suspended'
  source      TEXT,
  UNIQUE(league, game_date, home_ts_id, away_ts_id)
);

CREATE TABLE player_batting_game (
  id INTEGER PRIMARY KEY,
  game_id        INTEGER NOT NULL REFERENCES game(id),
  person_id      INTEGER NOT NULL REFERENCES person(id),
  team_season_id INTEGER REFERENCES team_season(id),
  pa INTEGER, ab INTEGER, r INTEGER, h INTEGER, hr INTEGER, rbi INTEGER,
  bb INTEGER, so INTEGER, sb INTEGER,
  UNIQUE(game_id, person_id)
);

CREATE TABLE player_pitching_game (
  id INTEGER PRIMARY KEY,
  game_id        INTEGER NOT NULL REFERENCES game(id),
  person_id      INTEGER NOT NULL REFERENCES person(id),
  team_season_id INTEGER REFERENCES team_season(id),
  ip_outs INTEGER, h INTEGER, r INTEGER, er INTEGER,
  bb INTEGER, so INTEGER, hr INTEGER, pitches INTEGER,
  decision TEXT,                    -- 'W'|'L'|'S'|'H'|NULL
  UNIQUE(game_id, person_id)
);

-- ===== 보조(Supplementary) =====
CREATE TABLE award_share (
  id INTEGER PRIMARY KEY,
  person_id INTEGER REFERENCES person(id),
  season_id INTEGER REFERENCES season(id),
  award     TEXT,                   -- 'MVP','CyYoung','GoldenGlove'
  vote_pct  REAL,
  won       INTEGER                 -- 0/1
);

CREATE TABLE postseason_series (    -- 우승 시리즈 포함 모든 포스트시즌 시리즈
  id INTEGER PRIMARY KEY,
  season_id    INTEGER REFERENCES season(id),
  league       TEXT NOT NULL,       -- 'MLB'|'KBO'|'NPB'
  round        TEXT NOT NULL,       -- 'WorldSeries'|'JapanSeries'|'KoreanSeries'|'LCS'|'PlayOff'|'WildCard'...
  is_championship INTEGER DEFAULT 0,-- 1 = 해당 리그 최종 우승 결정전(WS/일본/한국시리즈)
  winner_ts_id INTEGER REFERENCES team_season(id),
  loser_ts_id  INTEGER REFERENCES team_season(id),
  wins INTEGER, losses INTEGER, ties INTEGER DEFAULT 0,
  mvp_person_id INTEGER REFERENCES person(id),
  source TEXT,
  UNIQUE(season_id, league, round)
);

CREATE TABLE postseason_game (      -- 시리즈 내 개별 경기(선택 — game 테이블 재사용 가능)
  id INTEGER PRIMARY KEY,
  series_id INTEGER NOT NULL REFERENCES postseason_series(id),
  game_id   INTEGER REFERENCES game(id),
  game_no   INTEGER,                -- 시리즈 N차전
  UNIQUE(series_id, game_no)
);

-- ===== 리그 규칙 & 구단 로고 =====
CREATE TABLE league_rule (          -- 공통/리그 고유 규칙을 시점별 키-값으로
  id INTEGER PRIMARY KEY,
  league          TEXT NOT NULL,    -- 'MLB'|'KBO'|'NPB'
  rule_key        TEXT NOT NULL,    -- 'dh'|'tie_allowed'|'playoff_format'|'team_count'|'season_games'
  rule_value      TEXT,
  valid_from_year INTEGER,
  valid_to_year   INTEGER,          -- NULL = 현재 적용
  note            TEXT
);

CREATE TABLE team_logo (            -- 구단 로고 변천사 (프랜차이즈 단위 시점 매핑)
  id INTEGER PRIMARY KEY,
  franchise_id    INTEGER NOT NULL REFERENCES franchise(id),
  logo_type       TEXT,             -- 'primary'|'cap'|'alternate'|'wordmark'
  valid_from_year INTEGER,
  valid_to_year   INTEGER,          -- NULL = 현재 사용
  image_path      TEXT,             -- data/assets/logos/...
  source_url      TEXT,
  note            TEXT
);

CREATE INDEX idx_stint_person  ON stint(person_id);
CREATE INDEX idx_stint_ts      ON stint(team_season_id);
CREATE INDEX idx_game_date      ON game(game_date);
CREATE INDEX idx_pbg_person     ON player_batting_game(person_id);
CREATE INDEX idx_ppg_person     ON player_pitching_game(person_id);
CREATE INDEX idx_logo_franchise ON team_logo(franchise_id);
CREATE INDEX idx_rule_league     ON league_rule(league, rule_key);
```

---

## 5. 데이터 소스

| 리그 | T1 시즌 | T2 경기 | 수집 방식 |
|---|---|---|---|
| MLB | Lahman DB (CSV, 역사 전체) | Retrosheet game logs / MLB StatsAPI | CSV 다운로드, `pybaseball` |

> ⚠️ Lahman 소스 주의: 원조 `chadwickbureau/baseballdatabank` 저장소가 오프라인(404)이라
> 활성 미러 `infonuum/baseballdatabank`(2023.1 릴리스 = **2022 시즌까지**)를 사용 중.
> 2023+ 시즌은 공개 CSV 에 없음 → StatsAPI 등 별도 소스 필요. `mlb_lahman.LAHMAN_BASE` 상수로 분리.
| KBO | Statiz · KBO기록실 | KBO 공식 경기 기록 | 크롤링 (요청 간격 준수) |
| NPB | NPB 공식 · Baseball-Reference | NPB 공식 박스스코어 | 크롤링 |

추가 데이터:
- **우승 시리즈**: 각 리그 공식 기록(월드시리즈/일본시리즈/한국시리즈 결과·MVP)·위키피디아 요약. `postseason_series.is_championship = 1`로 표시.
- **구단 로고**: 로고는 **상표·저작권 보호 대상**이다. 무단 재배포는 피하고, ① 출처 URL만 `source_url`에 기록하거나 ② 개인·비상업 용도로 라이선스·이용 약관을 확인한 자료만 `data/assets/logos/`에 보관한다. 변천 연도·디자인 메타데이터(텍스트)는 자유롭게 저장 가능.

- 크롤링 시 `robots.txt`·요청 간격 준수, 원본 응답은 `data/raw/`에 캐시 후 재파싱(재요청 최소화).
- 소스마다 컬럼명·단위·이름 표기가 다르므로 **수집기는 staging까지만, 정규화는 normalize 단계에서** 일괄 처리.

---

## 6. 수집 파이프라인

```
raw (원본 캐시)  →  staging (소스별 정제)  →  normalize (코어 스키마 매핑)  →  load (SQLite upsert)
```

- **백필(backfill)**: 과거 전체를 한 번에. 날짜/시즌 범위를 인자로 받는다.
- **증분(daily)**: 종료된 어제·오늘 경기만. 같은 수집기에 `--since YYYY-MM-DD`만 다르게 전달.
- 모든 load는 **멱등(idempotent) upsert** — UNIQUE 제약으로 재실행해도 중복 안 생기게.
- "당일 경기"는 `ingest/daily.py`가 담당. 추후 cron/스케줄러로 일 1회 실행.

---

## 7. 기술 스택 & 디렉토리 구조

- 백엔드: Python + FastAPI / 저장: SQLite (분석 무거워지면 DuckDB 분석 레이어 추가)
- 프론트: React + Vite
- 개발: VS Code + Claude CLI

```
baseball-archive/
├── PROJECT_BRIEF.md
├── data/
│   ├── raw/            # 원본 캐시 — .gitignore, 모델 컨텍스트 로드 금지
│   ├── staging/        # 정제 중간 산출물
│   ├── assets/
│   │   └── logos/      # 구단 로고 이미지(라이선스 확인분만)
│   └── baseball.db     # SQLite
├── backend/
│   ├── app/
│   │   ├── main.py     # FastAPI 엔트리
│   │   ├── db.py
│   │   ├── models/     # SQLAlchemy/Pydantic
│   │   └── routers/    # /players /teams /games /postseason /logos ...
│   ├── ingest/
│   │   ├── sources/
│   │   │   ├── mlb_lahman.py
│   │   │   ├── kbo_statiz.py
│   │   │   ├── npb_official.py
│   │   │   ├── postseason.py   # 우승 시리즈
│   │   │   └── logos.py        # 로고 변천 메타
│   │   ├── normalize/  # staging → 코어 매핑
│   │   ├── load/       # 코어 → SQLite upsert
│   │   └── daily.py    # 당일 증분 수집
│   ├── migrations/     # 001_core.sql, 002_game.sql, 003_postseason_rules_logos.sql ...
│   └── tests/
├── frontend/           # React + Vite
│   └── src/
│       ├── leagues/    # 리그별 페이지 분리
│       │   ├── mlb/
│       │   ├── kbo/
│       │   └── npb/
│       ├── shared/     # 공통 컴포넌트(선수 카드, 스탯 테이블)
│       └── pages/
│           ├── PlayerCareer/   # 크로스리그 통합 커리어 뷰
│           ├── TeamHistory/    # 로고 변천 타임라인 포함
│           └── Postseason/     # 우승 시리즈
└── scripts/
```

---

## 8. 개발 단계 (depth-first)

> 한 리그·한 깊이를 완전히 작동시키고 다음으로 넘어간다. MLB가 데이터가 가장 풍부해 검증용 첫 슬라이스로 적합.

- **Phase 0 — 스캐폴딩** ✅: repo, 디렉토리, `migrations/001_core.sql` 적용, FastAPI 헬스체크.
- **Phase 1 — MLB 시즌 스탯(T1)** ✅: Lahman 적재. franchise/team_season/person/batting·pitching·fielding_season. **검증 첫 슬라이스.**
  - 적재: `mlb_lahman.{download,inspect,load}` — `load --season YYYY` 멱등 upsert.
  - 마이그레이션 006: `franchise(league, code)` UNIQUE 인덱스 추가.
  - 검증: `backend/tests/test_phase1.py` (HR 1위·pa 파생·멀티스틴트·ip_outs 정수·provenance·멱등).
  - API: `GET /players/{source}/{external_id}/career` (크로스리그 커리어 진입점).
- **Phase 2 — MLB 경기 단위(T2)** ✅: game / player_batting_game / player_pitching_game.
  - 소스: 공개·무키 MLB StatsAPI(`backend/ingest/sources/mlb_statsapi.py`) — `inspect <date>` / `backfill --start --end`. 원본 JSON 은 `data/raw/statsapi/<date>/` 캐시.
  - 인물 mlbam 연결: Chadwick register(key_bbref→key_mlbam)로 기존 person 에 mlbam external_id 추가 → 폴백(이름+생일) → 신규 생성.
  - 검증: `backend/tests/test_phase2.py` (15경기 슬라이스·승패투수 쌍·ip_outs 정수·라인 정합·provenance·멱등).
  - API: `GET /games?date=YYYY-MM-DD`, `GET /games/{id}`(박스스코어).
  - ⚠️ 알려진 한계(전체 백필 전 보강 필요): ① `innings` 는 `scheduledInnings`(9) 근사 — 연장/콜드는 linescore 로 정밀화. ② 더블헤더는 `game` UNIQUE(league,date,home,away)로 충돌 → `game_number` 컬럼 필요(schema-guardian).
- **Phase 3 — KBO 시즌 스탯(T1)** ✅: 프랜차이즈 lineage(해태→KIA 등)는 005 시드에 존재.
  - 소스 전환 경위: Statiz 는 `robots.txt`가 모든 봇(Claude 포함) 차단 → 사용 불가. **KBO 공식 기록실(`/Record/`)은 robots 허용 + 서버렌더 + 무키** 라 이쪽 채택(약관 확인 완료). 정찰 노트 `data/raw/kbo/_scout/RECON.md`.
  - 소스: `backend/ingest/sources/kbo_official.py` — ASP.NET viewstate **2단계 POST**(ddlSeason→ddlTeam 캐스케이드) + `ucPager` 페이지네이션 + 캐시. `inspect`/`backfill --year`. 원본 `data/raw/kbo/<year>/` 캐시.
  - 인물: `('kbo', playerId)` 안정 식별자(타자·투수 동일선수 자동 병합). name_native=한글, name_roman=NULL(Phase 5 보강).
  - 컬럼: 타자 HitterBasic/Basic1+Basic2 머지, 투수 PitcherBasic/Basic1, 순위 TeamRank(승/패/**무**). IP `"75 1/3"`→`ip_outs` 226.
  - 검증: `backend/tests/test_phase3.py`(2024: 10팀 경기=W+L+T=144, KIA 87-55-2 1위, HR왕 데이비슨 46, 멱등). API: `GET /leagues/KBO/standings?year=`.
  - ⚠️ 결손: 타자 SB/CS(RunningBasic 별도), 투수 GS/CG/SHO/BK/WP/BF(Pitcher Basic2 별도), name_roman.
- **Phase 4 — NPB 시즌 스탯(T1)** ✅: 무승부·센트럴/퍼시픽 계층 반영. (Phase 3보다 먼저 진행)
  - 소스: NPB 공식 npb.jp(`backend/ingest/sources/npb_official.py`, robots 404=허용, 폴리트 크롤). `inspect <year> <page>` / `backfill --year`. 원본 HTML `data/raw/npb/<year>/` 캐시.
  - franchise 12 생성(CL/PL 6:6), team_season 순위 W-L-T(전 팀 무승부>0), 투구 IP 2컬럼→`ip_outs` 정수 환산.
  - 검증: `backend/tests/test_phase4.py`. API: `GET /leagues/{code}/standings?year=`.
  - ⚠️ 한계: BIS 통계표가 **규정타석/규정이닝 위주**라 전체 로스터 아님(batting 48/pitching 66). `name_roman` 은 소스에 로마자가 없어 전건 NULL(Phase 5에서 보강). 전체 로스터는 팀별 상세 페이지 추가 크롤 필요.
- **Phase 5 — 크로스리그 인물 매칭** ✅: person_external_id 통합, 리그 이동 선수 1인 1행 병합.
  - NPB(한자, 로마자·생일·공유ID 없음)↔MLB 자동 매칭 불가 → **큐레이션 크로스워크 + 병합 엔진**(`backend/ingest/normalize/person_match.py`). `CROSSWALK`(mlbam ↔ 한자명) → `merge_persons` 가 person 참조 6개 FK(external_id/stint/award/postseason mvp/배팅·투구 game)를 repoint 후 중복 person 삭제. 멱등.
  - 병합 정책: name_native ← 한자(원어), name_roman ← MLB 로마자(NPB 로마자 결손 보강).
  - 데모: 鈴木誠也/Seiya Suzuki — NPB 広島 2021 + MLB Cubs 2022 가 한 person 으로 통합(mlbam·lahman 어느 진입점이든 통합 커리어).
  - 검증: `backend/tests/test_phase5.py`. API: `GET /players/multi-league`, `GET /players/{source}/{external_id}/career`(크로스리그).
  - ⚠️ NPB 합성키가 시즌별이라 다(多)시즌 NPB 선수는 시즌마다 person 분리됨 — 매칭 시 한자명으로 묶어 해소(merge 가 다시즌 NPB stint 를 한 person 에 모음).
  - **이동선수 확대 → 크로스리그 인물 8명**. `person_match` 는 NPB+KBO(`source IN ('npb','kbo')`) 원어 이름으로 매칭, CROSSWALK canonical=('lahman',playerID).
    - NPB↔MLB 6명: 鈴木誠也·ダルビッシュ有·田中将大(NPB 2013 24-0→MLB→NPB 복귀)·前田健太·川崎宗則·福留孝介. (NPB 2006/2010/2011/2013/2021/2022 적재)
    - KBO↔MLB 2명: **류현진**(한화 2010→MLB 다저스/블루제이스→**한화 2024 복귀** 라운드트립)·**김하성**(키움 2020→파드리스). (KBO 2010/2020 적재)
  - 재현: 해당 NPB/KBO 연도 `backfill` 후 `python -m backend.ingest.normalize.person_match run`.
  - ⚠️ 병합 불가 케이스: **이정후**(MLB 2024 데뷔 → 우리 MLB 미러 2022까지라 MLB person 부재, KBO 단독 적재됨 — MLB 2024 확보 시 자동 연결). **松井秀喜·이치로 등 2005 이전 NPB 이적** — npb.jp BIS 가 2005 미만 stats 미제공(404).
- **Phase 6 — 우승 시리즈 & 보조 데이터** ✅: postseason_series(월드/일본/한국시리즈 + MVP), award_share, 순위표, `league_rule`.
  - 마이그레이션 007: `award_share(person_id, season_id, award)` UNIQUE 인덱스(멱등 upsert용).
  - 소스 `backend/ingest/sources/postseason.py` — MLB는 Lahman SeriesPost(2022 포스트시즌 11개 시리즈) data-driven, NPB/KBO 우승시리즈는 큐레이션. `download`/`load`.
  - **우승 결정전 4개**(is_championship=1): MLB WS 2022 HOU>PHI(MVP Jeremy Pena), NPB 일본시리즈 2021 YS>ORX(中村悠平)·2022 ORX>YS(杉本裕太郎), KBO 한국시리즈 2024 KIA>SS(김선빈). 일본시리즈 무승부(ties=1) 반영.
  - award_share: MLB 2022 수상자 6명(MVP/CyYoung/RookieOfYear, won=1) 큐레이션.
  - 검증: `backend/tests/test_phase6.py`. API: `GET /postseason/seasons`(보유 시즌), `GET /postseason/championships`, `GET /postseason?league=&year=`.
  - **역대 확대(deep history)**: `python scripts/backfill_mlb_history.py` (opt-in 무거운 백필, 표준 `--fresh` 게이트 미포함, 멱등):
    1. `mlb_lahman.backfill_teams(1903,2022)` — team_season 만 가볍게(breadth). franchID 기준이라 과거 팀(브루클린 다저스→LAD)도 현재 프랜차이즈에 연결.
    2. `mlb_lahman.backfill_full(1955,2021)` — **WS MVP 시대 풀로드**(person/stat, depth, CSV 1회 읽기). `--no-full` 로 생략.
    3. `postseason.load()` → **MLB 포스트시즌 1903~2022 / 118 월드시리즈 / 373 시리즈**, **WS MVP 67/67**(1955~2022, 1994 파업 제외) 채움. 예: 1956 Don Larsen, 2009 Hideki Matsui.
  - ⚠️ 한계: 공개 Lahman 미러 Awards CSV가 2016까지라 2022 수상 **투표 지분(vote_pct)** 원본 없음(수상자 won=1만 큐레이션). 1903~1954 월드시리즈는 WS MVP 상이 없던 시대라 mvp NULL(정상).
- **Phase 7 — 구단 로고 변천사** ✅: team_logo 메타 + 팀 히스토리 타임라인.
  - 마이그레이션 008: `team_logo(franchise_id, logo_type, valid_from_year)` UNIQUE 인덱스.
  - 소스 `backend/ingest/sources/logos.py` — franchise.lineage 파싱. **KBO**는 연도 포함이라 연도별 era 정확 적재(WO 우리/넥센/키움 3개, KIA 해태/KIA 2개, 해체구단 HD/SB 닫음). **NPB/MLB**는 연도 경계 없어 baseline 1개 era(과거명은 note 보존).
  - **저작권 준수**: 로고 이미지 미저장(`image_path` 전부 NULL), **출처 링크(source_url)+메타데이터만**. team_logo 64행.
  - 검증: `backend/tests/test_phase7.py`. API: `GET /franchises/{code}/history?league=`(계보+로고 era+시즌별 팀명).
  - ⚠️ NPB/MLB 는 lineage 에 연도가 없어 단일 era. 다(多)era 가 필요하면 큐레이션 연도 추가 필요. MLB founded_year NULL.
- **Phase 8 — 당일 증분 파이프라인** ✅: `daily.py` + 멱등 upsert 검증.
  - `backend/ingest/daily.py` — `run(since, until=오늘)` 이 백필과 **동일한 game-level 수집기**(mlb_statsapi.backfill)를 날짜 범위만 좁혀 호출. 종료(Final) 정규시즌 경기만, 멱등.
  - game-level(T2) 수집기가 MLB StatsAPI 뿐이라 daily 는 MLB 경기 증분(NPB/KBO 는 T1만 구현 → daily 대상 아님).
  - 검증: `backend/tests/test_phase8.py`(2022-04-16/17 증분 추가 + 재실행 멱등 + Final/정규/statsapi). API: `GET /status`(리그별 커버리지·최근 경기일 = 증분 기준점).
  - ⚠️ 실제 '오늘' 증분은 해당 시즌 team_season 이 적재돼 있어야 연결됨 — 현재 MLB 는 2022만(Lahman 미러 한계)이라 2026 '오늘' 경기는 시즌 미적재로 스킵. 라이브 운영하려면 현재 시즌 team_season/person 백필 선행 필요.
- **Phase 9 — 프론트엔드(리그별 페이지 분리)** ✅: 리그 공통 vs 고유 규칙 반영, 선수 커리어(크로스리그)·팀 역대사(로고 변천)·포스트시즌 뷰.
  - 스캐폴드: React+Vite(`frontend/`), `npm run build` 통과. 개발 서버 `/api/*` → FastAPI 프록시(`vite.config.js`), CORS 불필요. 공통 `src/shared/LeagueBadge`, API 클라이언트 `src/api.js`.
  - **4개 슬라이스 완성**:
    1. **리그 홈**(`src/leagues/LeagueHome`): `/leagues`(리그 규칙) + `/status`(보유 시즌) + `/leagues/{code}/standings`. 서브리그 그룹(MLB 지구/NPB CL·PL/KBO 단일). "저장 통합·표현 리그 분리"의 프론트 마무리.
    2. **선수 커리어**(`src/pages/PlayerCareer`): `/players/multi-league` → `/players/{source}/{id}/career`. 크로스리그 통합(鈴木誠也 NPB 2021+MLB 2022).
    3. **팀 히스토리**(`src/pages/TeamHistory`): `/franchises/{code}/history`. 로고 변천 타임라인(이미지 미저장·출처 링크) + 시즌 기록.
    4. **포스트시즌**(`src/pages/Postseason`): `/postseason/seasons` + `/postseason?league=&year=`. 역대 플레이오프 전 라운드 브래킷 진행순(MLB 2022 와카~월드시리즈).
  - 실행: 백엔드 `uvicorn backend.app.main:app --reload` + 프론트 `cd frontend && npm run dev` → http://localhost:5173

각 Phase 완료 기준: 마이그레이션 적용 + 적재 + 검증 테스트 통과 + 해당 API 엔드포인트 1개 동작.

---

## 9. Claude CLI 작업 지침

- **원본 파일을 컨텍스트에 붙이지 않는다.** 항상 `df.shape`, `df.columns`, `df.head()` 요약만 보고 매핑을 설계.
- 수집기는 **각자 독립 실행 가능**하게(`python -m ingest.sources.mlb_lahman --season 2023`).
- 마이그레이션은 순번 매긴 `.sql` 파일로만 추가. 기존 파일 수정 대신 새 마이그레이션.
- 코어 규칙 재확인: `ip_outs` 정수 / `ties` 컬럼 / `source` provenance / 이름 원어+로마자.
- load는 전부 멱등 upsert. UNIQUE 제약 먼저 확인.
- 한 번에 한 Phase. Phase 경계를 넘는 변경은 먼저 이 문서를 갱신하고 진행.

### 검증 테스트 예시
- MLB 2023시즌 HR 합계가 공개된 리그 총계와 일치하는가.
- 트레이드 선수의 시즌 stint 2개가 합산 시 단일 시즌 총계와 맞는가.
- `ip_outs` 합산 후 이닝 환산이 표준 표기와 일치하는가.
- 같은 경기를 두 번 적재해도 행 수가 늘지 않는가(멱등성).

---

## 10. 다음 액션
1. `data/` `backend/` `frontend/` 디렉토리 생성, `.gitignore`에 `data/raw/`·`*.db` 추가.
2. `migrations/001_core.sql`에 §4 DDL 반영 후 적용.
3. Lahman CSV를 `data/raw/`에 받아 `df.columns`만 확인 → Phase 1 매핑 설계.
