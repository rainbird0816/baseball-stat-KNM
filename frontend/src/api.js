// 백엔드 API 클라이언트. 개발 시 vite proxy(/api → 127.0.0.1:8000)를 거친다.
const BASE = "/api";

async function get(path) {
  const res = await fetch(BASE + path);
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${res.status} ${path} ${detail}`.trim());
  }
  return res.json();
}

export const api = {
  // 크로스리그 이동 선수 목록 (Phase 5)
  multiLeaguePlayers: () => get("/players/multi-league"),
  // 통합 커리어 (source: 'mlbam'|'lahman'|'kbo'|'npb' 등)
  playerCareer: (source, externalId) =>
    get(`/players/${source}/${encodeURIComponent(externalId)}/career`),

  // 리그 목록 + 규칙 (org 레벨)
  leagues: () => get("/leagues"),
  // 리그별 프랜차이즈 목록
  franchises: (league) => get(`/leagues/${league}/franchises`),
  // 프랜차이즈 히스토리 (계보 + 로고 변천 + 시즌) — Phase 7
  franchiseHistory: (code, league) =>
    get(`/franchises/${encodeURIComponent(code)}/history?league=${league}`),

  // 포스트시즌 — Phase 6 (역대 플레이오프 브라우징)
  postseasonSeasons: () => get("/postseason/seasons"),
  postseasonSeries: (league, year) =>
    get(`/postseason?league=${league}&year=${year}`),

  // 리그별 홈 — 적재 커버리지(보유 시즌) + 순위표
  status: () => get("/status"),
  standings: (league, year) =>
    get(`/leagues/${league}/standings?year=${year}`),
};
