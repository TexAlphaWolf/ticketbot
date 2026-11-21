import { useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router";
import { api, type Stats as StatsData } from "../api";
import { Card, ErrorBox, Loading, PersonChip } from "../components/ui";
import { duration } from "../format";
import { useI18n } from "../i18n";
import { useGuild } from "./Overview";

const PERIODS = ["7", "30", "90", "all"] as const;
type Period = (typeof PERIODS)[number];

function Bars({ data, label }: { data: [string, number][]; label: (key: string) => string }) {
  const max = Math.max(1, ...data.map(([, n]) => n));
  return (
    <ul className="bars">
      {data.map(([key, n]) => (
        <li key={key}>
          <span className="bar-label">{label(key)}</span>
          <span className="bar-track"><span className="bar" style={{ width: `${(n / max) * 100}%` }} /></span>
          <strong>{n}</strong>
        </li>
      ))}
    </ul>
  );
}

export function Stats() {
  const { t } = useI18n();
  const { guildId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const period = (PERIODS.find((p) => p === params.get("period")) ?? "30") as Period;
  const guild = useGuild(guildId);
  const stats = useQuery({
    queryKey: ["stats", guildId, period],
    queryFn: () => api<StatsData>(`/guilds/${guildId}/stats?period=${period}`),
    enabled: guild.data?.can_see_stats === true,
  });

  if (guild.data && !guild.data.can_see_stats) return <p className="card muted">{t("stats.not_allowed")}</p>;
  const s = stats.data;
  const time = (v: number | null) => (v === null ? "–" : duration(v));

  return (
    <>
      <h1>{t("stats.title")}</h1>
      <div className="filters">
        <div className="segmented" role="group">
          {PERIODS.map((p) => (
            <button key={p} className={p === period ? "active" : ""} onClick={() => setParams({ period: p }, { replace: true })}>
              {t(`stats.period.${p}`)}
            </button>
          ))}
        </div>
      </div>
      {stats.isPending ? <Loading /> : stats.isError ? <ErrorBox error={stats.error} retry={() => stats.refetch()} /> : s && (
        <>
          <div className="stats-row">
            {([["stats.opened", s.opened], ["stats.closed", s.closed], ["stats.open", s.open], ["stats.unclaimed", s.unclaimed]] as const)
              .map(([key, value]) => (
                <div key={key} className="card stat"><span className="stat-value">{value}</span><span className="muted">{t(key)}</span></div>
              ))}
            <div className="card stat"><span className="stat-value">{time(s.avg_first_response)}</span><span className="muted">{t("stats.first_response")}</span></div>
            <div className="card stat"><span className="stat-value">{time(s.avg_resolution)}</span><span className="muted">{t("stats.resolution")}</span></div>
            <div className="card stat">
              <span className="stat-value">{s.avg_rating === null ? "–" : `${s.avg_rating.toFixed(1)} ⭐`}</span>
              <span className="muted">{t("stats.rating")} · {t("stats.ratings", { n: s.ratings })}</span>
            </div>
          </div>
          <div className="columns-even">
            <Card title={t("stats.by_type")}>
              <Bars data={Object.entries(s.by_type)} label={(k) => k} />
            </Card>
            <Card title={t("stats.by_priority")}>
              <Bars data={Object.entries(s.by_priority)} label={(k) => t(`priority.${k as "low" | "medium" | "high" | "none"}`)} />
            </Card>
          </div>
          {(s.faq_solved > 0 || s.faq_opened > 0) && (
            <Card title={t("stats.faq")}>
              <Bars data={[["solved", s.faq_solved], ["opened", s.faq_opened]]}
                label={(k) => t(k === "solved" ? "stats.faq_solved" : "stats.faq_opened")} />
            </Card>
          )}
          {s.leaderboard.length > 0 && (
            <Card title={t("stats.leaderboard")}>
              <table className="tickets">
                <thead><tr><th>{t("stats.leaderboard")}</th><th>{t("stats.handled")}</th><th>{t("stats.rating")}</th><th>{t("stats.first_response")}</th></tr></thead>
                <tbody>
                  {s.leaderboard.map((row) => (
                    <tr key={row.staff_id}>
                      <td><PersonChip id={row.staff_id} people={s.people} /></td>
                      <td>{row.handled}</td>
                      <td>{row.avg_rating === null ? "–" : `${row.avg_rating.toFixed(1)} ⭐ (${row.ratings})`}</td>
                      <td>{time(row.avg_first_response)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </>
      )}
    </>
  );
}
