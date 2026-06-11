-- 006_franchise_unique.sql
-- franchise 에 (league, code) 유니크 제약 추가.
--
-- 의도:
--   Phase 1 MLB Lahman 적재 시 franchise 멱등 upsert(ON CONFLICT(league, code))
--   를 쓰려면 (league, code) 에 유니크 제약이 필요하다. 제약이 없어 loader 가
--   lookup-or-insert 로 우회 중이었다. 중복 프랜차이즈 방지 + 깔끔한 upsert 를 위해 추가.
--
-- 구현 노트:
--   SQLite 는 기존 테이블에 ALTER 로 UNIQUE 제약을 추가할 수 없다.
--   대신 UNIQUE INDEX 를 만든다. 유니크 인덱스는 ON CONFLICT(league, code) 의
--   conflict target 으로도 그대로 동작한다.
--   IF NOT EXISTS 로 멱등 — --fresh 든 기존 DB 든 안전하게 재적용 가능.
--
-- 사전 확인: 기존 데이터(KBO 12 + MLB 30)에 (league, code) 중복 없음 검증 완료.

CREATE UNIQUE INDEX IF NOT EXISTS idx_franchise_league_code
  ON franchise(league, code);
