# baseball-archive

KBO · NPB · MLB 세 리그의 팀/타자/투수 데이터를 하나의 통합 SQLite DB로 수집·정규화하는 프로젝트.
시즌 누적 스탯, 경기 단위 박스스코어, 우승 시리즈, 구단 로고 변천사, 팀 역대 역사까지.

전체 설계는 **[PROJECT_BRIEF.md](./PROJECT_BRIEF.md)** 참고 (Claude CLI 작업의 단일 진실 소스).

## 지금까지 만들어진 것 (스캐폴딩 완료)
- 디렉토리 구조 (backend / ingest / migrations / frontend / data)
- 마이그레이션 5종 (`backend/migrations/001~005`) — 코어/시즌/경기/우승·규칙·로고/시드
- 검증된 SQLite DB 생성기 (`scripts/init_db.py`)
- 레퍼런스 시드 — 리그 계층, 리그 규칙(DH·무승부·팀수), KBO 프랜차이즈 계보(초안)
- Lahman → 코어 매핑 (`backend/ingest/normalize/lahman_mapping.py`, `docs/lahman_mapping.md`)
- FastAPI 골격 (`/health`, `/leagues`, `/leagues/{code}/franchises`)
- 멱등 upsert 로더, 수집기 스텁, 스키마 테스트
- **Claude Code 워크플로 레이어** (`.claude/` + `CLAUDE.md`):
  - `CLAUDE.md` — 매 턴 로드되는 불변 규칙
  - 서브에이전트 3종 — `ingest-builder` / `schema-guardian` / `data-verifier`(읽기 전용)
  - `settings.json` — 권한 허용 + **`data/raw` 직접 Read 차단**(원본 컨텍스트 주입 방지)
  - `.mcp.json` — (선택) SQLite MCP 로 DB 직접 조회
  - 슬래시 커맨드 — `/verify`, `/next-phase`

> 외부 API 키는 필요 없음. 모든 소스가 무료·무키(Lahman CSV / 공개 StatsAPI / pybaseball / 크롤링).
> `.mcp.json` 의 `mcp-server-sqlite` 패키지는 환경에서 사용 가능 여부를 한 번 확인할 것(미사용 시 파일 삭제 가능).

## 퀵스타트
```bash
# 1) (선택) 가상환경
python -m venv .venv && source .venv/bin/activate

# 2) 의존성
pip install -r requirements.txt

# 3) DB 생성 (마이그레이션 + 시드 적용)
python scripts/init_db.py --fresh

# 4) 스키마 테스트
python -m backend.tests.test_schema        # 또는: pytest backend/tests/

# 5) API 서버
uvicorn backend.app.main:app --reload
#   http://127.0.0.1:8000/docs
#   http://127.0.0.1:8000/leagues
```

## 다음 단계 (VS Code + Claude CLI)
- **Phase 1 — MLB 시즌 스탯 적재**: baseballdatabank CSV 를 `data/raw/lahman/` 에 두고
  `python -m backend.ingest.sources.mlb_lahman inspect Batting` 으로 컬럼 확인 →
  `lahman_mapping` 으로 `load()` 구현.
- 이후 Phase 2(경기) → 3(KBO) → 4(NPB) → 5(크로스리그 매칭) → 6(우승 시리즈) → 7(로고) → 8(증분) → 9(프론트).

## 원칙 (요약)
- 원본 CSV/HTML 은 모델 컨텍스트에 넣지 않는다 — 컬럼/요약만.
- 이닝은 아웃 정수(`ip_outs`), 무승부 `ties` 컬럼 필수, 이름 원어+로마자 병기.
- 모든 적재는 멱등 upsert. 마이그레이션은 순번 `.sql` 추가(기존 수정 금지).
- 저장은 통합 1 DB, 표현·규칙은 리그 분리.
- 로고 등 상표·저작권 자료는 출처 링크/메타 위주, 라이선스 확인분만 보관.
