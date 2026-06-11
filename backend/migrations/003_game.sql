-- 003_game.sql — 팩트: 경기 단위 (T2)

CREATE TABLE IF NOT EXISTS game (
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

CREATE TABLE IF NOT EXISTS player_batting_game (
  id INTEGER PRIMARY KEY,
  game_id        INTEGER NOT NULL REFERENCES game(id),
  person_id      INTEGER NOT NULL REFERENCES person(id),
  team_season_id INTEGER REFERENCES team_season(id),
  pa INTEGER, ab INTEGER, r INTEGER, h INTEGER, hr INTEGER, rbi INTEGER,
  bb INTEGER, so INTEGER, sb INTEGER,
  UNIQUE(game_id, person_id)
);

CREATE TABLE IF NOT EXISTS player_pitching_game (
  id INTEGER PRIMARY KEY,
  game_id        INTEGER NOT NULL REFERENCES game(id),
  person_id      INTEGER NOT NULL REFERENCES person(id),
  team_season_id INTEGER REFERENCES team_season(id),
  ip_outs INTEGER, h INTEGER, r INTEGER, er INTEGER,
  bb INTEGER, so INTEGER, hr INTEGER, pitches INTEGER,
  decision TEXT,                    -- 'W'|'L'|'S'|'H'|NULL
  UNIQUE(game_id, person_id)
);

CREATE INDEX IF NOT EXISTS idx_game_date  ON game(game_date);
CREATE INDEX IF NOT EXISTS idx_game_season ON game(season_id);
CREATE INDEX IF NOT EXISTS idx_pbg_person ON player_batting_game(person_id);
CREATE INDEX IF NOT EXISTS idx_ppg_person ON player_pitching_game(person_id);
