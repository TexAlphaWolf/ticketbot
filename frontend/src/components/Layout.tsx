import { useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet, useNavigate, useParams } from "react-router";
import { api, type GuildDetail, type GuildSummary, type Me } from "../api";
import { LANGS, type Lang, useI18n } from "../i18n";
import { useLiveUpdates } from "../live";
import { Avatar } from "./ui";

export function Layout({ me }: { me: Me }) {
  const { t, lang, setLang } = useI18n();
  const { guildId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const guilds = useQuery({ queryKey: ["guilds"], queryFn: () => api<GuildSummary[]>("/guilds") });
  const current = guilds.data?.find((g) => g.id === guildId);
  const detail = useQuery({
    queryKey: ["guild", guildId],
    queryFn: () => api<GuildDetail>(`/guilds/${guildId}`),
    enabled: !!current,
  });
  const name = me.user.global_name ?? me.user.username;
  const live = useLiveUpdates(current?.id);

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    queryClient.clear();
    navigate("/");
    window.location.reload();
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <NavLink to="/" className="brand" end>
          <img src="/favicon.svg" alt="" width={28} height={28} />
          {t("app.title")}
        </NavLink>
        <nav aria-label={t("nav.servers")}>
          <p className="sidebar-label">{t("nav.servers")}</p>
          {guilds.data?.map((g) => (
            <NavLink key={g.id} to={`/servers/${g.id}`} className="sidebar-server" title={g.name}>
              <Avatar src={g.icon_url} name={g.name} size={28} />
              <span>{g.name}</span>
            </NavLink>
          ))}
        </nav>
        {current && (
          <nav className="sidebar-section" aria-label={current.name}>
            <NavLink to={`/servers/${current.id}`} end>
              {t("nav.overview")}
            </NavLink>
            <NavLink to={`/servers/${current.id}/tickets`}>{t("nav.tickets")}</NavLink>
            {detail.data?.can_see_stats && <NavLink to={`/servers/${current.id}/stats`}>{t("nav.stats")}</NavLink>}
            <span className={`live ${live ? "live-on" : ""}`} title={live ? t("live.on") : t("live.off")}>
              <span className="live-dot" aria-hidden /> {live ? t("live.on") : t("live.off")}
            </span>
          </nav>
        )}
        {current?.role === "admin" && (
          <nav className="sidebar-section" aria-label={t("nav.manage")}>
            <p className="sidebar-label">{t("nav.manage")}</p>
            <NavLink to={`/servers/${current.id}/settings`}>{t("nav.settings")}</NavLink>
            <NavLink to={`/servers/${current.id}/types`}>{t("nav.types")}</NavLink>
            <NavLink to={`/servers/${current.id}/faq`}>{t("nav.faq")}</NavLink>
            <NavLink to={`/servers/${current.id}/escalation`}>{t("nav.escalation")}</NavLink>
          </nav>
        )}
        <div className="sidebar-footer">
          <label className="lang">
            <span className="visually-hidden">{t("nav.language")}</span>
            <select value={lang} onChange={(e) => setLang(e.target.value as Lang)}>
              {Object.entries(LANGS).map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <div className="me">
            <Avatar src={me.user.avatar_url} name={name} size={32} />
            <div>
              <strong>{name}</strong>
              <span className="muted">@{me.user.username}</span>
            </div>
          </div>
          <button className="button button-ghost" onClick={logout}>
            {t("nav.logout")}
          </button>
        </div>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
