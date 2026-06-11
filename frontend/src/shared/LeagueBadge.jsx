// 리그 색상 배지. 리그별 표현 분리(공통 컴포넌트, 리그마다 색만 다름).
const COLORS = {
  MLB: { bg: "#1b3a6b", fg: "#ffffff" },
  NPB: { bg: "#9b1b30", fg: "#ffffff" },
  KBO: { bg: "#1d6b46", fg: "#ffffff" },
};

export default function LeagueBadge({ league }) {
  const c = COLORS[league] || { bg: "#444", fg: "#fff" };
  return (
    <span
      className="league-badge"
      style={{ background: c.bg, color: c.fg }}
      title={league}
    >
      {league}
    </span>
  );
}
