-- 001_core.sql — 차원(Dimension) + 인물 + 참여
-- SQLite. PRAGMA foreign_keys 는 런타임에 init_db.py 가 ON 으로 켠다.

-- ===== 차원(Dimension) =====
CREATE TABLE IF NOT EXISTS organization (    -- 자기참조 리그 계층
  id          INTEGER PRIMARY KEY,
  parent_id   INTEGER REFERENCES organization(id),
  level       TEXT NOT NULL,        -- 'org' | 'subleague' | 'division'
  name        TEXT NOT NULL,        -- 'MLB','American League','AL East','KBO','NPB','Central'
  short_code  TEXT
);

CREATE TABLE IF NOT EXISTS franchise (
  id           INTEGER PRIMARY KEY,
  league       TEXT NOT NULL,       -- 'MLB' | 'KBO' | 'NPB'
  code         TEXT NOT NULL,       -- 안정 식별자 (예: 'KIA')
  lineage      TEXT,                -- '해태 타이거즈(1982)→KIA 타이거즈(2001)'
  founded_year INTEGER
);

CREATE TABLE IF NOT EXISTS season (
  id      INTEGER PRIMARY KEY,
  league  TEXT NOT NULL,
  year    INTEGER NOT NULL,
  UNIQUE(league, year)
);

CREATE TABLE IF NOT EXISTS park (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL,
  city        TEXT,
  park_factor REAL
);

CREATE TABLE IF NOT EXISTS team_season (
  id            INTEGER PRIMARY KEY,
  franchise_id  INTEGER NOT NULL REFERENCES franchise(id),
  season_id     INTEGER NOT NULL REFERENCES season(id),
  org_id        INTEGER REFERENCES organization(id),  -- 그 시즌 소속(지구/리그)
  park_id       INTEGER REFERENCES park(id),
  team_name     TEXT NOT NULL,      -- 그 시즌 명칭 '해태 타이거즈'
  city          TEXT,
  wins          INTEGER,
  losses        INTEGER,
  ties          INTEGER DEFAULT 0,  -- NPB/KBO 무승부
  source        TEXT,
  UNIQUE(franchise_id, season_id)
);

-- ===== 인물 & 참여 =====
CREATE TABLE IF NOT EXISTS person (
  id          INTEGER PRIMARY KEY,
  name_native TEXT,                 -- 원어 (송병화 / 大谷翔平)
  name_roman  TEXT,                 -- 로마자 (Song Byeong-hwa / Ohtani)
  birth_date  TEXT,
  bats        TEXT,                 -- 'L'|'R'|'S'
  throws      TEXT,                 -- 'L'|'R'
  debut_date  TEXT
);

CREATE TABLE IF NOT EXISTS person_external_id (
  person_id   INTEGER NOT NULL REFERENCES person(id),
  source      TEXT NOT NULL,        -- 'mlbam','bbref','statiz','npb','retrosheet','fangraphs'
  external_id TEXT NOT NULL,
  PRIMARY KEY (source, external_id)
);

CREATE TABLE IF NOT EXISTS stint (   -- 시즌 중 트레이드 시 1인 다중 stint
  id              INTEGER PRIMARY KEY,
  person_id       INTEGER NOT NULL REFERENCES person(id),
  team_season_id  INTEGER NOT NULL REFERENCES team_season(id),
  primary_pos     TEXT,
  jersey          TEXT,
  order_in_season INTEGER DEFAULT 1,
  UNIQUE(person_id, team_season_id, order_in_season)
);

CREATE INDEX IF NOT EXISTS idx_stint_person ON stint(person_id);
CREATE INDEX IF NOT EXISTS idx_stint_ts     ON stint(team_season_id);
CREATE INDEX IF NOT EXISTS idx_ts_franchise ON team_season(franchise_id);
CREATE INDEX IF NOT EXISTS idx_ts_season    ON team_season(season_id);
