-- 004_postseason_rules_logos.sql — 보조: 우승 시리즈 / 수상 / 리그 규칙 / 구단 로고

CREATE TABLE IF NOT EXISTS award_share (
  id INTEGER PRIMARY KEY,
  person_id INTEGER REFERENCES person(id),
  season_id INTEGER REFERENCES season(id),
  award     TEXT,                   -- 'MVP','CyYoung','GoldenGlove','RookieOfYear'
  vote_pct  REAL,
  won       INTEGER                 -- 0/1
);

CREATE TABLE IF NOT EXISTS postseason_series (   -- 우승 시리즈 포함 모든 포스트시즌 시리즈
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

CREATE TABLE IF NOT EXISTS postseason_game (     -- 시리즈 내 개별 경기(선택 — game 재사용)
  id INTEGER PRIMARY KEY,
  series_id INTEGER NOT NULL REFERENCES postseason_series(id),
  game_id   INTEGER REFERENCES game(id),
  game_no   INTEGER,                -- 시리즈 N차전
  UNIQUE(series_id, game_no)
);

CREATE TABLE IF NOT EXISTS league_rule (         -- 공통/리그 고유 규칙을 시점별 키-값으로
  id INTEGER PRIMARY KEY,
  league          TEXT NOT NULL,    -- 'MLB'|'KBO'|'NPB'
  rule_key        TEXT NOT NULL,    -- 'dh'|'tie_allowed'|'playoff_format'|'team_count'|'season_games'
  rule_value      TEXT,
  valid_from_year INTEGER,
  valid_to_year   INTEGER,          -- NULL = 현재 적용
  note            TEXT
);

CREATE TABLE IF NOT EXISTS team_logo (           -- 구단 로고 변천사 (프랜차이즈 단위 시점 매핑)
  id INTEGER PRIMARY KEY,
  franchise_id    INTEGER NOT NULL REFERENCES franchise(id),
  logo_type       TEXT,             -- 'primary'|'cap'|'alternate'|'wordmark'
  valid_from_year INTEGER,
  valid_to_year   INTEGER,          -- NULL = 현재 사용
  image_path      TEXT,             -- data/assets/logos/...  (라이선스 확인분만)
  source_url      TEXT,
  note            TEXT
);

CREATE INDEX IF NOT EXISTS idx_logo_franchise ON team_logo(franchise_id);
CREATE INDEX IF NOT EXISTS idx_rule_league    ON league_rule(league, rule_key);
CREATE INDEX IF NOT EXISTS idx_award_person   ON award_share(person_id);
CREATE INDEX IF NOT EXISTS idx_series_season  ON postseason_series(season_id);
