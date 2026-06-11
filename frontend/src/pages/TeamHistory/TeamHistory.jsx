import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import LeagueBadge from "../../shared/LeagueBadge";

const LEAGUE_ORDER = ["KBO", "NPB", "MLB"]; // KBO 가 로고 변천이 가장 풍부 → 기본 먼저

// lineage 의 마지막 구단명(현재 정체성)만 뽑아 목록에 표시.
function currentName(lineage) {
  if (!lineage) return "";
  const last = lineage.split("→").pop().trim();
  return last.replace(/\(.*?\)/g, "").trim(); // 괄호(연도) 제거
}

// 팀 역대사 뷰: 리그 → 프랜차이즈 → 로고 변천 타임라인 + 시즌 기록.
export default function TeamHistory() {
  const { league, code } = useParams();
  const navigate = useNavigate();
  const activeLeague = league || "KBO";

  const [leagues, setLeagues] = useState([]);
  const [franchises, setFranchises] = useState([]);
  const [history, setHistory] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .leagues()
      .then((rows) => {
        const codes = rows.map((r) => r.short_code);
        codes.sort((a, b) => LEAGUE_ORDER.indexOf(a) - LEAGUE_ORDER.indexOf(b));
        setLeagues(codes);
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    setFranchises([]);
    api.franchises(activeLeague).then(setFranchises).catch((e) => setError(String(e)));
  }, [activeLeague]);

  useEffect(() => {
    if (!code) {
      setHistory(null);
      return;
    }
    setError(null);
    api.franchiseHistory(code, activeLeague).then(setHistory).catch((e) => setError(String(e)));
  }, [code, activeLeague]);

  return (
    <div className="career-layout">
      <aside className="mover-list">
        <h2>팀 역대사</h2>
        <div className="league-tabs">
          {leagues.map((lg) => (
            <button
              key={lg}
              className={lg === activeLeague ? "tab active" : "tab"}
              onClick={() => navigate(`/teams/${lg}`)}
            >
              {lg}
            </button>
          ))}
        </div>
        <ul>
          {franchises.map((f) => {
            const active = f.code === code;
            return (
              <li key={f.code}>
                <button
                  className={active ? "mover active" : "mover"}
                  onClick={() => navigate(`/teams/${activeLeague}/${encodeURIComponent(f.code)}`)}
                >
                  <span className="mover-name">{currentName(f.lineage) || f.code}</span>
                  <span className="mover-native">
                    {f.code}
                    {f.founded_year ? ` · ${f.founded_year}~` : ""}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </aside>

      <main className="career-detail">
        {error && <p className="error">에러: {error}</p>}
        {!code && !error && <p className="muted big">← 팀을 선택하세요.</p>}
        {history && <HistoryDetail history={history} league={activeLeague} />}
      </main>
    </div>
  );
}

function HistoryDetail({ history, league }) {
  const { franchise, logo_eras, seasons } = history;
  return (
    <div>
      <header className="player-head">
        <h1>{currentName(franchise.lineage) || franchise.code}</h1>
        <span className="native">{franchise.code}</span>
        <span className="leagues">
          <LeagueBadge league={league} />
        </span>
      </header>

      {franchise.lineage && <p className="lineage">{franchise.lineage}</p>}

      <section>
        <h3>로고·정체성 변천</h3>
        <p className="copyright-note">
          로고 이미지는 상표·저작권 보호 대상이라 저장하지 않습니다 — 연도·명칭과 출처 링크만 표시.
        </p>
        <ol className="timeline">
          {logo_eras.map((e, i) => (
            <li key={i}>
              <span className="years">
                {e.valid_from_year ?? "?"}–{e.valid_to_year ?? "현재"}
              </span>
              <span className="era-note">{e.note}</span>
              {e.source_url && (
                <a className="src" href={e.source_url} target="_blank" rel="noreferrer">
                  출처
                </a>
              )}
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h3>시즌 기록</h3>
        {seasons.length === 0 ? (
          <p className="muted">적재된 시즌이 없습니다.</p>
        ) : (
          <table className="stat-table">
            <thead>
              <tr>
                <th>연도</th><th>팀명</th><th>승</th><th>패</th><th>무</th>
              </tr>
            </thead>
            <tbody>
              {seasons.map((s) => (
                <tr key={s.year}>
                  <td>{s.year}</td>
                  <td className="team">{s.team_name}</td>
                  <td>{s.wins}</td><td>{s.losses}</td><td>{s.ties}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
