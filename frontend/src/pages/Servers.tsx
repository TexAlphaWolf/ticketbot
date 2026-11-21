import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { api, type GuildSummary } from "../api";
import { Avatar, ErrorBox, Loading } from "../components/ui";
import { useI18n } from "../i18n";

export function Servers() {
  const { t } = useI18n();
  const guilds = useQuery({ queryKey: ["guilds"], queryFn: () => api<GuildSummary[]>("/guilds") });
  if (guilds.isPending) return <Loading />;
  if (guilds.isError) return <ErrorBox error={guilds.error} retry={() => guilds.refetch()} />;
  return (
    <>
      <h1>{t("servers.title")}</h1>
      {guilds.data.length === 0 ? (
        <p className="card muted">{t("servers.none")}</p>
      ) : (
        <div className="grid">
          {guilds.data.map((g) => (
            <Link key={g.id} to={`/servers/${g.id}`} className="card server-card">
              <Avatar src={g.icon_url} name={g.name} size={48} />
              <div>
                <strong>{g.name}</strong>
                <span className={`badge badge-role-${g.role}`}>{t(`role.${g.role}`)}</span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
