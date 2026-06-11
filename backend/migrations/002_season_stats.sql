-- 002_season_stats.sql — 팩트: 시즌 누적 스탯 (T1)

CREATE TABLE IF NOT EXISTS batting_season (
  stint_id INTEGER PRIMARY KEY REFERENCES stint(id),
  g INTEGER, pa INTEGER, ab INTEGER, r INTEGER, h INTEGER,
  b2 INTEGER, b3 INTEGER, hr INTEGER, rbi INTEGER,
  sb INTEGER, cs INTEGER, bb INTEGER, so INTEGER,
  ibb INTEGER, hbp INTEGER, sh INTEGER, sf INTEGER, gidp INTEGER,
  extra JSON,                       -- wRC+, OPS+, wOBA 등 희소·파생 지표
  source TEXT
);

CREATE TABLE IF NOT EXISTS pitching_season (
  stint_id INTEGER PRIMARY KEY REFERENCES stint(id),
  w INTEGER, l INTEGER, g INTEGER, gs INTEGER, cg INTEGER, sho INTEGER,
  sv INTEGER, hld INTEGER, ip_outs INTEGER,            -- 이닝은 아웃 정수
  h INTEGER, r INTEGER, er INTEGER, hr INTEGER,
  bb INTEGER, so INTEGER, hbp INTEGER, bk INTEGER, wp INTEGER, bf INTEGER,
  extra JSON,                       -- FIP, ERA+, xFIP 등
  source TEXT
);

CREATE TABLE IF NOT EXISTS fielding_season (
  id INTEGER PRIMARY KEY,
  stint_id INTEGER NOT NULL REFERENCES stint(id),
  pos TEXT NOT NULL,
  g INTEGER, gs INTEGER, inn_outs INTEGER,
  po INTEGER, a INTEGER, e INTEGER, dp INTEGER,
  pb INTEGER, sb_c INTEGER, cs_c INTEGER,              -- 포수 한정
  UNIQUE(stint_id, pos)
);
