-- 007_award_share_unique.sql
-- award_share 에 (person_id, season_id, award) 유니크 제약 추가.
--
-- 의도:
--   Phase 6 보조 데이터 적재 시 award_share(MVP/사이영 등 수상 투표 지분)를
--   멱등 upsert 하려면 ON CONFLICT(person_id, season_id, award) 의 conflict
--   target 이 필요하다. 004 에서 만든 award_share 에는 유니크 제약이 없어
--   ON CONFLICT 를 쓸 수 없었다.
--
--   (person_id, season_id, award) 는 안전한 자연키다 — 한 선수가 한 시즌에
--   같은 상(MVP, CyYoung 등)을 두 번 받지 않으므로 중복이 발생하지 않는다.
--
-- 구현 노트:
--   SQLite 는 기존 테이블에 ALTER 로 UNIQUE 제약을 추가할 수 없다.
--   대신 UNIQUE INDEX 를 만든다. 유니크 인덱스는
--   ON CONFLICT(person_id, season_id, award) 의 conflict target 으로도 동작한다.
--   IF NOT EXISTS 로 멱등 — --fresh 든 기존 DB 든 안전하게 재적용 가능.
--
-- 사전 확인: 현재 award_share 0행, (person_id, season_id, award) 중복 없음 검증 완료.

CREATE UNIQUE INDEX IF NOT EXISTS idx_award_share_natural
  ON award_share(person_id, season_id, award);
