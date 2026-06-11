import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import LeagueBadge from "../../shared/LeagueBadge";

// 크로스리그 통합 커리어 뷰 (Phase 9 첫 슬라이스).
// 좌: 리그 이동 선수 목록 / 우: 선택한 선수의 NPB·MLB·KBO 통합 커리어.
export default function PlayerCareer() {
  const { source, id } = useParams();
  const navigate = useNavigate();
  const [movers, setMovers] = useState([]);
  const [career, setCareer] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.multiLeaguePlayers().then(setMovers).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!source || !id) {
      setCareer(null);
      return;
    }
    setLoading(true);
    setError(null);
    api
      .playerCareer(source, id)
      .then(setCareer)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [source, id]);

  return (
    <div className="career-layout">
      <aside className="mover-list">
        <h2>리그 이동 선수</h2>
        <p className="hint">두 개 이상 리그에서 뛴 통합 인물</p>
        {movers.length === 0 && <p className="muted">불러오는 중…</p>}
        <ul>
          {movers.map((m) => {
            const active = source === m.ref_source && id === m.ref_id;
            return (
              <li key={m.id}>
                <button
                  className={active ? "mover active" : "mover"}
                  onClick={() =>
                    navigate(`/career/${m.ref_source}/${encodeURIComponent(m.ref_id)}`)
                  }
                >
                  <span className="mover-name">{m.name_roman}</span>
                  <span className="mover-native">{m.name_native}</span>
                  <span className="mover-leagues">
                    {String(m.leagues || "")
                      .split(",")
                      .filter(Boolean)
                      .map((lg) => (
                        <LeagueBadge key={lg} league={lg} />
                      ))}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </aside>

      <main className="career-detail">
        {error && <p className="error">에러: {error}</p>}
        {!source && !error && (
          <p className="muted big">← 왼쪽에서 선수를 선택하세요.</p>
        )}
        {loading && <p className="muted">불러오는 중…</p>}
        {career && <CareerDetail career={career} />}
      </main>
    </div>
  );
}

function CareerDetail({ career }) {
  const { person, seasons } = career;
  const leagues = [...new Set(seasons.map((s) => s.league))];
  const batting = seasons.filter((s) => s.batting);
  const pitching = seasons.filter((s) => s.pitching);

  return (
    <div>
      <header className="player-head">
        <h1>{person.name_roman || person.name_native}</h1>
        {person.name_roman && person.name_native && (
          <span className="native">{person.name_native}</span>
        )}
        <span className="leagues">
          {leagues.map((lg) => (
            <LeagueBadge key={lg} league={lg} />
          ))}
        </span>
      </header>

      {batting.length > 0 && (
        <section>
          <h3>타격</h3>
          <table className="stat-table">
            <thead>
              <tr>
                <th>연도</th><th>리그</th><th>팀</th>
                <th>G</th><th>PA</th><th>AB</th><th>H</th>
                <th>2B</th><th>3B</th><th>HR</th><th>RBI</th>
                <th>SB</th><th>BB</th><th>SO</th>
              </tr>
            </thead>
            <tbody>
              {batting.map((s, i) => (
                <tr key={i}>
                  <td>{s.year}</td>
                  <td><LeagueBadge league={s.league} /></td>
                  <td className="team">{s.team_name}</td>
                  <td>{s.bat_g}</td><td>{s.pa}</td><td>{s.ab}</td><td>{s.h}</td>
                  <td>{s.b2}</td><td>{s.b3}</td><td className="hi">{s.hr}</td><td>{s.rbi}</td>
                  <td>{s.sb}</td><td>{s.bb}</td><td>{s.so}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {pitching.length > 0 && (
        <section>
          <h3>투구</h3>
          <table className="stat-table">
            <thead>
              <tr>
                <th>연도</th><th>리그</th><th>팀</th>
                <th>G</th><th>W</th><th>L</th><th>SV</th>
                <th>IP</th><th>H</th><th>ER</th><th>SO</th><th>BB</th>
              </tr>
            </thead>
            <tbody>
              {pitching.map((s, i) => (
                <tr key={i}>
                  <td>{s.year}</td>
                  <td><LeagueBadge league={s.league} /></td>
                  <td className="team">{s.team_name}</td>
                  <td>{s.pit_g}</td><td>{s.w}</td><td>{s.l}</td><td>{s.sv}</td>
                  <td>{s.ip}</td><td>{s.p_h}</td><td>{s.er}</td><td>{s.p_so}</td><td>{s.p_bb}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
