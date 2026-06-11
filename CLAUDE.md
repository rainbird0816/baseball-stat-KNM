# CLAUDE.md — baseball-archive

상세 설계·단계는 `PROJECT_BRIEF.md`, 데이터 매핑은 `docs/lahman_mapping.md`.
이 파일은 **매 턴 지켜야 할 불변 규칙**만 담는다(항상 로드됨).

## 불변 규칙
- **원본 CSV/HTML 을 컨텍스트에 넣지 않는다.** `df.columns` / `df.head(3)` / `shape` 요약만 본다.
  (raw 파일 직접 Read 는 settings 로 차단됨 — `inspect` 스크립트로만 확인)
- **이닝은 아웃 정수(`ip_outs`)로 저장.** 출력 시에만 `outs//3`, `outs%3`.
- **무승부 `ties` 컬럼을 항상 채운다**(NPB/KBO).
- **선수 이름은 원어(`name_native`) + 로마자(`name_roman`) 병기.**
- **출처 `source`(provenance) 컬럼을 남긴다.**
- **모든 적재는 멱등 upsert**(`backend/ingest/load/loader.py`). 재실행해도 행이 늘면 안 된다.
- **마이그레이션은 순번 `.sql` 새 파일로만 추가.** 기존 마이그레이션 수정·삭제 금지.
- **저장은 통합 1 DB, 표현·규칙은 리그 분리**(`league_rule` + 프론트 리그별 페이지).
- **상표·저작권 자료(구단 로고 등)는 출처 링크/메타 위주.** 라이선스 확인분만 `data/assets/logos/`.
- **외부 API 키가 필요한 소스는 쓰지 않는다**(Lahman CSV / 공개 StatsAPI / pybaseball / 크롤링).

## 작업 규율
- 한 번에 한 Phase. Phase 경계를 넘는 변경은 `PROJECT_BRIEF.md` 를 먼저 갱신.
- **"완료" 선언 전 반드시 통과**: `python scripts/init_db.py --fresh && python -m backend.tests.test_schema`
- 노이즈 큰 검증/대조는 `data-verifier` 서브에이전트에 위임(읽기 전용).

## 명령
- DB 빌드: `python scripts/init_db.py --fresh`
- 테스트: `python -m backend.tests.test_schema`  (또는 `pytest backend/tests/`)
- 서버: `uvicorn backend.app.main:app --reload`  → http://127.0.0.1:8000/docs
- 원본 컬럼 확인: `python -m backend.ingest.sources.mlb_lahman inspect <Table>`

## 서브에이전트 (.claude/agents)
- `ingest-builder` — 수집·정규화 코드 작성/수정
- `schema-guardian` — 마이그레이션/DDL 변경
- `data-verifier` — 적재 결과·스키마 검증(읽기 전용)
