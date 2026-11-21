import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { api, channelUrl, type TicketDetail } from "../api";
import { TicketActions } from "../components/TicketActions";
import { Card, DiscordText, ErrorBox, Loading, PersonChip, PriorityLabel, StatusBadge } from "../components/ui";
import { dateTime, duration } from "../format";
import { useI18n } from "../i18n";
import { useGuild } from "./Overview";
import { ticketTitle } from "./Tickets";

export function Ticket() {
  const { t, lang } = useI18n();
  const { guildId = "", ticketId = "" } = useParams();
  const ticket = useQuery({
    queryKey: ["ticket", guildId, ticketId],
    queryFn: () => api<TicketDetail>(`/guilds/${guildId}/tickets/${ticketId}`),
  });
  const guild = useGuild(guildId);
  if (ticket.isPending) return <Loading />;
  if (ticket.isError) return <ErrorBox error={ticket.error} retry={() => ticket.refetch()} />;
  const d = ticket.data;
  const people = d.people;
  const open = d.status !== "closed" && d.channel_id !== null;
  const levels = guild.data?.escalation_levels ?? 0;

  return (
    <>
      <Link to={`/servers/${guildId}/tickets`} className="back">
        ← {t("ticket.back")}
      </Link>
      <header className="page-header">
        <span className="emoji big">{d.type_emoji.startsWith("<") ? "🎫" : d.type_emoji}</span>
        <div>
          <h1>{ticketTitle(d)}</h1>
          <div className="row">
            <StatusBadge status={d.status} />
            <PriorityLabel priority={d.priority} />
            <span className="muted">{d.type_label}</span>
            {d.is_thread && <span className="muted">· {t("ticket.thread")}</span>}
          </div>
        </div>
        {d.channel_id && (
          <a className="button" href={channelUrl(guildId, d.channel_id)} target="_blank" rel="noreferrer">
            {t("ticket.open_discord")}
          </a>
        )}
      </header>

      <div className="columns">
        <div className="column-main">
          <Card title={t("ticket.subject")}>
            {d.subject || d.description ? (
              <>
                <p className="subject">{d.subject}</p>
                {d.description && (
                  <>
                    <h3>{t("ticket.answers")}</h3>
                    <DiscordText text={d.description} />
                  </>
                )}
              </>
            ) : (
              <p className="muted">{t("ticket.no_content")}</p>
            )}
          </Card>
          {open && <TicketActions guildId={guildId} ticket={d} levels={levels} part="main" />}
          <Card title={t("ticket.notes")}>
            {d.notes.length === 0 ? (
              <p className="muted">{t("ticket.no_notes")}</p>
            ) : (
              <ul className="notes">
                {d.notes.map((n, i) => (
                  <li key={i}>
                    <div className="row">
                      <PersonChip id={n.author_id} people={people} />
                      <span className="muted small">{dateTime(n.created_at, lang)}</span>
                    </div>
                    <p className="prewrap">{n.text}</p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <aside className="column-side">
          <Card>
            <dl className="facts">
              <dt>{t("tickets.col.owner")}</dt>
              <dd><PersonChip id={d.owner_id} people={people} /></dd>
              <dt>{t("tickets.col.staff")}</dt>
              <dd><PersonChip id={d.claimed_by ?? d.assigned_to} people={people} /></dd>
              <dt>{t("ticket.opened")}</dt>
              <dd>{dateTime(d.opened_at, lang)}</dd>
              {d.first_response_at && (
                <>
                  <dt>{t("ticket.first_response")}</dt>
                  <dd>{duration(d.first_response_at - d.opened_at)}</dd>
                </>
              )}
              {d.escalation_level > 0 && (
                <>
                  <dt>{t("ticket.escalation")}</dt>
                  <dd>⬆️ {d.escalation_level}</dd>
                </>
              )}
              {d.closed_at && (
                <>
                  <dt>{t("ticket.closed")}</dt>
                  <dd>{dateTime(d.closed_at, lang)}</dd>
                  <dt>{t("ticket.closed_by")}</dt>
                  <dd><PersonChip id={d.closed_by} people={people} /></dd>
                  {d.close_reason && (
                    <>
                      <dt>{t("ticket.reason")}</dt>
                      <dd>{d.close_reason}</dd>
                    </>
                  )}
                </>
              )}
              {d.rating && (
                <>
                  <dt>{t("ticket.rating")}</dt>
                  <dd>
                    {"⭐".repeat(d.rating)}
                    {d.rating_comment && <span className="block muted">“{d.rating_comment}”</span>}
                  </dd>
                </>
              )}
            </dl>
          </Card>
          {open && <TicketActions guildId={guildId} ticket={d} levels={levels} part="side" />}
        </aside>
      </div>
    </>
  );
}
