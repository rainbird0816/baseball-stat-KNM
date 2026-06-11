-- 005_seed_reference.sql — 스크래핑 없이 채울 수 있는 레퍼런스 데이터
-- ※ 연도/계보는 초안. VS Code에서 공식 자료로 검증 후 확정할 것.

-- ===== 리그 계층 (organization) =====
INSERT OR IGNORE INTO organization (id, parent_id, level, name, short_code) VALUES
  (1,  NULL, 'org',       'Major League Baseball', 'MLB'),
  (2,  1,    'subleague', 'American League',        'AL'),
  (3,  1,    'subleague', 'National League',        'NL'),
  (4,  2,    'division',  'AL East',                'ALE'),
  (5,  2,    'division',  'AL Central',             'ALC'),
  (6,  2,    'division',  'AL West',                'ALW'),
  (7,  3,    'division',  'NL East',                'NLE'),
  (8,  3,    'division',  'NL Central',             'NLC'),
  (9,  3,    'division',  'NL West',                'NLW'),
  (20, NULL, 'org',       'Nippon Professional Baseball', 'NPB'),
  (21, 20,   'subleague', 'Central League',         'CL'),
  (22, 20,   'subleague', 'Pacific League',         'PL'),
  (30, NULL, 'org',       'Korea Baseball Organization', 'KBO');

-- ===== 리그 규칙 (league_rule) =====
INSERT INTO league_rule (league, rule_key, rule_value, valid_from_year, valid_to_year, note) VALUES
  ('MLB','dh','AL only',     1973, 2021, '아메리칸리그 지명타자 도입'),
  ('MLB','dh','universal',   2022, NULL, '내셔널리그 포함 전면 도입'),
  ('MLB','tie_allowed','no', NULL, NULL, '연장으로 승부, 무승부 사실상 없음'),
  ('MLB','team_count','30',  1998, NULL, '30개 구단 체제'),
  ('NPB','dh','Pacific only',1975, NULL, '퍼시픽리그만 지명타자, 센트럴리그 미적용'),
  ('NPB','tie_allowed','yes',NULL, NULL, '정규시즌 연장 후 무승부 인정'),
  ('NPB','team_count','12',  NULL, NULL, '센트럴 6 + 퍼시픽 6'),
  ('KBO','dh','yes',         1982, NULL, '창설부터 지명타자제'),
  ('KBO','tie_allowed','yes',NULL, NULL, '정규시즌 연장 후 무승부 인정'),
  ('KBO','team_count','10',  2015, NULL, 'kt 위즈 합류로 10개 구단');

-- ===== KBO 프랜차이즈 계보 (초안 — 연도 검증 필요) =====
INSERT INTO franchise (league, code, lineage, founded_year) VALUES
  ('KBO','KIA','해태 타이거즈(1982)→KIA 타이거즈(2001)',                       1982),
  ('KBO','OB', 'OB 베어스(1982)→두산 베어스(1999)',                            1982),
  ('KBO','LG', 'MBC 청룡(1982)→LG 트윈스(1990)',                              1982),
  ('KBO','SS', '삼성 라이온즈(1982~)',                                         1982),
  ('KBO','LT', '롯데 자이언츠(1982~)',                                         1982),
  ('KBO','HH', '빙그레 이글스(1986)→한화 이글스(1994)',                        1986),
  ('KBO','SK', 'SK 와이번스(2000)→SSG 랜더스(2021)',                          2000),
  ('KBO','WO', '우리 히어로즈(2008)→넥센 히어로즈(2010)→키움 히어로즈(2019)',  2008),
  ('KBO','NC', 'NC 다이노스(2013~)',                                           2013),
  ('KBO','KT', 'kt 위즈(2015~)',                                               2015),
  -- 해체 구단(참고)
  ('KBO','HD', '삼미 슈퍼스타즈(1982)→청보 핀토스(1985)→태평양 돌핀스(1988)→현대 유니콘스(1996)→해체(2007)', 1982),
  ('KBO','SB', '쌍방울 레이더스(1991~1999, 해체)',                             1991);
