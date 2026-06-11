import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import LeagueBadge from "../../shared/LeagueBadge";

const ROUND_LABEL = {
  WorldSeries: "월드시리즈",
  JapanSeries: "일본시리즈",
  KoreanSeries: "한국시리즈",
};

// 라운드를 브래킷 진행 순서(와카→디비전→리그→우승)로 정렬하기 위한 가중치.
function roundWeight(s) {
  if (s.is_championship) return 5;
  const r = s.round || "";
  if (r.includes("WC")) return 1;
  if (r.includes("DS")) return 2;
  if (r.includes("CS")) return 3;
  return 4;
}

function roundLabel(s) {
  return ROUND_LABEL[s.round] || s.round;
}

function score(s) {
  return s.ties > 0 ? `${s.wins}-${s.losses}-${s.ties}` : `${s.wins}-${s.losses}`;
}

// 포스트시즌 뷰: (리그·연도) 선택 → 그 시즌 전 라운드(역대 플레이오프 브라우징).
export default function Postseason() {
  const { league, year } = useParams();
  const navigate = useNavigate();
  const [seasons, setSeasons] = useState([]);
  const [series, setSeries] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.postseasonSeasons().then(setSeasons).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!league || !year) {
      setSeries(null);
      return;
    }
    setError(null);
    api
      .postseasonSeries(league, year)
      .then((rows) => setSeries([...rows].sort((a, b) => roundWeight(a) - roundWeight(b))))
      .catch((e) => setError(String(e)));
  }, [league, year]);

  return (
    <div className="career-layout">
      <aside className="mover-list">
        <h2>포스트시즌</h2>
        <p className="hint">역대 플레이오프 — 시즌을 고르세요</p>
        <ul>
          {seasons.map((s) => {
            const active = s.league === league && String(s.year) === year;
            return (
              <li key={`${s.league}-${s.year}`}>
                <button
                  className={active ? "mover active" : "mover"}
                  onClick={() => navigate(`/postseason/${s.league}/${s.year}`)}
                >
                  <span className="mover-name">
                    {s.year} <LeagueBadge league={s.league} />
                  </span>
                  <span className="mover-native">
                    {s.series_count} 시리즈{s.has_championship ? " · 우승 결정전 포함" : ""}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </aside>

      <main className="career-detail">
        {error && <p className="error">에러: {error}</p>}
        {!league && !error && <p className="muted big">← 시즌을 선택하세요.</p>}
        {series && (
          <div>
            <header className="player-head">
              <h1>{year} 포스트시즌</h1>
              <span className="leagues">
                <LeagueBadge league={league} />
              </span>
            </header>
            <ol className="series-list">
              {series.map((s, i) => (
                <li key={i} className={s.is_championship ? "series champ" : "series"}>
                  <div className="series-round">
                    {s.is_championship && <span className="trophy">🏆</span>}
                    {roundLabel(s)}
                  </div>
                  <div className="series-teams">
                    <span className="win">{s.winner_name || s.winner}</span>
                    <span className="vs">{score(s)}</span>
                    <span className="lose">{s.loser_name || s.loser}</span>
                  </div>
                  <div className="series-mvp">
                    {s.mvp_roman || s.mvp_native ? (
                      <>MVP {s.mvp_roman || s.mvp_native}</>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </div>
        )}
      </main>
    </div>
  );
}
