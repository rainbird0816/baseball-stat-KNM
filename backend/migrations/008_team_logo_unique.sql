-- 008_team_logo_unique.sql
-- team_logo 에 (franchise_id, logo_type, valid_from_year) 유니크 제약 추가.
--
-- 의도:
--   Phase 7 구단 로고 변천사 적재 시 team_logo 를 멱등 upsert 하려면
--   ON CONFLICT(franchise_id, logo_type, valid_from_year) 의 conflict target 이
--   필요하다. 004 에서 만든 team_logo 에는 유니크 제약이 없었다.
--
--   (franchise_id, logo_type, valid_from_year) 는 안전한 자연키다 — 한 프랜차이즈의
--   한 로고 종류(primary/cap/alternate/wordmark)는 같은 시작연도에 하나만 존재한다.
--
-- 구현 노트:
--   SQLite 는 기존 테이블에 ALTER 로 UNIQUE 제약을 추가할 수 없어 UNIQUE INDEX 로 만든다.
--   유니크 인덱스는 ON CONFLICT 의 conflict target 으로도 동작한다.
--   IF NOT EXISTS 로 멱등 — --fresh 든 기존 DB 든 안전하게 재적용 가능.
--
-- 사전 확인: 현재 team_logo 0행, 중복 없음.

CREATE UNIQUE INDEX IF NOT EXISTS idx_team_logo_natural
  ON team_logo(franchise_id, logo_type, valid_from_year);
