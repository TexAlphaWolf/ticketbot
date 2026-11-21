import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { api, type GuildDetail } from "../api";
import { Avatar, Card, ErrorBox, Loading } from "../components/ui";
import { useI18n } from "../i18n";

export function useGuild(guildId: string) {
  return useQuery({ queryKey: ["guild", guildId], queryFn: () => api<GuildDetail>(`/guilds/${guildId}`) });
}

export function Overview() {
  const { t } = useI18n();
  const { guildId = "" } = useParams();
  const guild = useGuild(guildId);
  if (guild.isPending) return <Loading />;
  if (guild.isError) return <ErrorBox error={guild.error} retry={() => guild.refetch()} />;
  const g = guild.data;
  return (
    <>
      <header className="page-header">
        <Avatar src={g.icon_url} name={g.name} size={48} />
        <div>
          <h1>{g.name}</h1>
          <span className={`badge badge-role-${g.role}`}>{t(`role.${g.role}`)}</span>
        </div>
      </header>
      <div className="stats-row">
        <Link to={`/servers/${g.id}/tickets?status=open`} className="card stat">
          <span className="stat-value">{g.waiting}</span>
          <span className="muted">{t("overview.waiting")}</span>
        </Link>
        <Link to={`/servers/${g.id}/tickets?status=open`} className="card stat">
          <span className="stat-value">{g.in_progress}</span>
          <span className="muted">{t("overview.in_progress")}</span>
        </Link>
      </div>
      <Card title={t("overview.types")}>
        <ul className="type-list">
          {g.types.map((type) => (
            <li key={type.key}>
              <Link to={`/servers/${g.id}/tickets?status=all&type=${encodeURIComponent(type.key)}`}>
                <span className="emoji">{type.emoji.startsWith("<") ? "🎫" : type.emoji}</span>
                <strong>{type.label}</strong>
                {type.description && <span className="muted"> · {type.description}</span>}
              </Link>
            </li>
          ))}
        </ul>
        <p className="muted small">
          {t("overview.mode")} {t(`mode.${g.ticket_mode}`)}
        </p>
      </Card>
    </>
  );
}
