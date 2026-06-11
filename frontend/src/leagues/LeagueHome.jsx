import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import LeagueBadge from "../shared/LeagueBadge";

const LEAGUE_ORDER = ["MLB", "NPB", "KBO"];

const RULE_LABEL = {
  dh: "지명타자(DH)",
  tie_allowed: "무승부",
  team_count: "팀 수",
  season_games: "정규시즌 경기",
  playoff_format: "플레이오프",
};

function yearRange(r) {
  const from = r.valid_from_year ? `${r.valid_from_year}~` : "";
  const to = r.valid_to_year ? `${r.valid_to_year}` : from ? "" : "";
  if (!from && !to) return "";
  return ` (${r.valid_from_year ?? "?"}~${r.valid_to_year ?? ""})`;
}

// 리그별 홈: 리그 고유 규칙 + 시즌 순위표(서브리그 그룹).
// "저장은 통합, 표현·규칙은 리그 분리" 원칙의 프론트 마무리.
export default function LeagueHome() {
  const { code } = useParams();
  const navigate = useNavigate();
  const [leagues, setLeagues] = useState([]);
  const [status, setStatus] = useState(null);
  const [year, setYear] = useState(null);
  const [standings, setStandings] = useState([]);
  const [error, setError] = useState(null);

  const active = code || "MLB";

  useEffect(() => {
    api.leagues().then(setLeagues).catch((e) => setError(String(e)));
    api.status().then(setStatus).catch((e) => setError(String(e)));
  }, []);

  const seasons = useMemo(() => {
    const s = status?.leagues?.[active]?.seasons || [];
    return [...s].sort((a, b) => b - a);
  }, [status, active]);

  // 리그가 바뀌면 가장 최근 시즌으로
  useEffect(() => {
    setYear(seasons.length ? seasons[0] : null);
  }, [active, seasons.length]);

  useEffect(() => {
    if (!year) {
      setStandings([]);
      return;
    }
    setError(null);
    api.standings(active, year).then(setStandings).catch((e) => setError(String(e)));
  }, [active, year]);

  const leagueCodes = useMemo(
    () =>
      leagues
        .map((l) => l.short_code)
        .sort((a, b) => LEAGUE_ORDER.indexOf(a) - LEAGUE_ORDER.indexOf(b)),
    [leagues]
  );
  const rules = leagues.find((l) => l.short_code === active)?.rules || [];

  // 순위표를 서브리그(MLB=지구, NPB=CL/PL, KBO=단일)별로 그룹
  const groups = useMemo(() => {
    const m = new Map();
    for (const r of standings) {
      const key = r.subleague_name || r.subleague || "";
      if (!m.has(key)) m.set(key, []);
      m.get(key).push(r);
    }
    return [...m.entries()];
  }, [standings]);

  return (
    <div className="league-home">
      <div className="league-tabs big">
        {leagueCodes.map((lg) => (
          <button
            key={lg}
            className={lg === active ? "tab active" : "tab"}
            onClick={() => navigate(`/leagues/${lg}`)}
          >
            <LeagueBadge league={lg} />
            <span className="tab-name">
              {leagues.find((l) => l.short_code === lg)?.name}
            </span>
          </button>
        ))}
      </div>

      {error && <p className="error">에러: {error}</p>}

      <div className="league-body">
        <aside className="rules-panel">
          <h3>리그 규칙</h3>
          {rules.length === 0 && <p className="muted">규칙 없음</p>}
          <dl>
            {rules.map((r, i) => (
              <div className="rule" key={i}>
                <dt>{RULE_LABEL[r.rule_key] || r.rule_key}</dt>
                <dd>
                  {r.rule_value}
                  <span className="muted">{yearRange(r)}</span>
                </dd>
              </div>
            ))}
          </dl>
        </aside>

        <main className="standings-main">
          <div className="year-chips">
            {seasons.map((y) => (
              <button
                key={y}
                className={y === year ? "chip active" : "chip"}
                onClick={() => setYear(y)}
              >
                {y}
              </button>
            ))}
            {seasons.length === 0 && <span className="muted">적재된 시즌 없음</span>}
          </div>

          {groups.map(([name, rows]) => (
            <section key={name}>
              {groups.length > 1 && <h3>{name}</h3>}
              <table className="stat-table">
                <thead>
                  <tr>
                    <th>팀</th><th>승</th><th>패</th><th>무</th><th>승률</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={i}>
                      <td className="team">{r.team_name}</td>
                      <td>{r.wins}</td><td>{r.losses}</td><td>{r.ties}</td>
                      <td>{r.win_pct != null ? r.win_pct.toFixed(3) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ))}
        </main>
      </div>
    </div>
  );
}
