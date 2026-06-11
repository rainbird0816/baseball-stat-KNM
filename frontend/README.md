# frontend (Phase 9)

React + Vite. 리그별 페이지를 분리한다(공통 규칙 + 리그 고유 규칙 공존).

아직 스캐폴드 전. Phase 9 진입 시:

```bash
npm create vite@latest . -- --template react
npm install
```

계획된 구조:
- `src/leagues/{mlb,kbo,npb}/` — 리그별 페이지·규칙 분기
- `src/shared/` — 공통 컴포넌트(선수 카드, 스탯 테이블)
- `src/pages/PlayerCareer/` — 크로스리그 통합 커리어 뷰
- `src/pages/TeamHistory/` — 로고 변천 타임라인 포함
- `src/pages/Postseason/` — 우승 시리즈

백엔드 API: `http://127.0.0.1:8000` (`/leagues`, `/leagues/{code}/franchises` ...)
