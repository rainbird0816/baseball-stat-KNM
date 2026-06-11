import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import PlayerCareer from "./pages/PlayerCareer/PlayerCareer";
import TeamHistory from "./pages/TeamHistory/TeamHistory";
import Postseason from "./pages/Postseason/Postseason";
import LeagueHome from "./leagues/LeagueHome";

// 앱 셸 + 라우팅. Phase 9 첫 슬라이스로 크로스리그 선수 커리어를 구현.
// (TeamHistory / Postseason / 리그별 페이지는 후속 슬라이스 — 네비 placeholder)
export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <h1 className="brand">⚾ baseball-archive</h1>
        <nav>
          <NavLink to="/leagues" className="navlink">리그</NavLink>
          <NavLink to="/career" className="navlink">선수 커리어</NavLink>
          <NavLink to="/teams" className="navlink">팀 히스토리</NavLink>
          <NavLink to="/postseason" className="navlink">포스트시즌</NavLink>
        </nav>
      </header>
      <Routes>
        <Route path="/" element={<Navigate to="/leagues" replace />} />
        <Route path="/leagues" element={<LeagueHome />} />
        <Route path="/leagues/:code" element={<LeagueHome />} />
        <Route path="/career" element={<PlayerCareer />} />
        <Route path="/career/:source/:id" element={<PlayerCareer />} />
        <Route path="/teams" element={<TeamHistory />} />
        <Route path="/teams/:league" element={<TeamHistory />} />
        <Route path="/teams/:league/:code" element={<TeamHistory />} />
        <Route path="/postseason" element={<Postseason />} />
        <Route path="/postseason/:league/:year" element={<Postseason />} />
        <Route path="*" element={<p style={{ padding: 24 }}>없는 페이지</p>} />
      </Routes>
    </div>
  );
}
