import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";
import { api, type Transcript } from "../api";
import { dateTime } from "../format";
import { useI18n } from "../i18n";
import { useRun } from "./toast";
import { Avatar, Card, DiscordText, ErrorBox, Loading } from "./ui";

export function TranscriptView({ guildId, ticketId, available, closedAt = null, mine = false }: {
  guildId: string; ticketId: number; available: boolean; closedAt?: number | null; mine?: boolean;
}) {
  const { t, lang } = useI18n();
  // Staff: /guilds/... (with the notes); the author of the ticket: /me/guilds/...
  const path = `${mine ? "/me" : ""}/guilds/${guildId}/tickets/${ticketId}/transcript`;
  const transcript = useQuery({
    queryKey: ["transcript", guildId, ticketId, mine],
    queryFn: () => api<Transcript>(path),
    enabled: available,
    staleTime: Infinity,
  });
  if (!available) {
    // The bot saves the transcript a few seconds after closing; the live updates bring it
    const saving = closedAt !== null && Date.now() / 1000 - closedAt < 120;
    return (
      <Card title={t("transcript.title")}>
        <p className="muted">{saving ? <><span className="spinner" aria-hidden /> {t("transcript.saving")}</> : t("transcript.none")}</p>
      </Card>
    );
  }
  if (transcript.isPending) return <Loading />;
  if (transcript.isError) return <ErrorBox error={transcript.error} retry={() => transcript.refetch()} />;
  const tr = transcript.data;
  return (
    <Card title={`${t("transcript.title")} · #${tr.channel_name}`}
      actions={mine ? undefined : <a className="button" href={`/api/v1/guilds/${guildId}/tickets/${ticketId}/transcript.html`} download>{t("transcript.download")}</a>}>
      {tr.messages.length === 0 && <p className="muted">{t("transcript.empty")}</p>}
      <ol className="transcript">
        {tr.messages.map((m, i) => (
          <li key={i}>
            <Avatar src={m.avatar} name={m.author} size={36} />
            <div className="message">
              <div className="row">
                <strong>{m.author}</strong>
                {m.bot && <span className="badge badge-bot">{t("transcript.bot")}</span>}
                <span className="muted small">{dateTime(m.created_at, lang)}</span>
              </div>
              {m.content && <DiscordText text={m.content} />}
              {m.embeds.map((e, j) => (
                <div key={j} className="embed">
                  {e.author && <div className="embed-author">{e.author}</div>}
                  {e.title && <strong className="block">{e.title}</strong>}
                  {e.description && <DiscordText text={e.description} />}
                  {e.fields.map(([name, value], k) => (
                    <div key={k} className="small"><strong>{name}</strong><DiscordText text={value} /></div>
                  ))}
                  {e.footer && <div className="embed-footer">{e.footer}</div>}
                </div>
              ))}
              {m.attachments.map((a, j) => (
                a.image ? (
                  <a key={j} className="attachment-image" href={a.url} target="_blank" rel="noreferrer">
                    <img src={a.url} alt={a.filename} loading="lazy"
                      onError={(e) => e.currentTarget.replaceWith(`📎 ${a.filename}`)} />
                  </a>
                ) : <a key={j} className="attachment" href={a.url} target="_blank" rel="noreferrer">📎 {a.filename}</a>
              ))}
              {m.stickers.map((st, j) => (
                <div key={j} className="sticker" title={`${st.name} · ID ${st.id}`}>
                  {st.image && <img src={st.url} alt={st.name} loading="lazy" onError={(e) => e.currentTarget.remove()} />}
                  <span className="muted small">🏷️ {t("transcript.sticker")}: {st.name}</span>
                </div>
              ))}
              {m.reactions.length > 0 && (
                <div className="reactions">
                  {m.reactions.map((r, j) => (
                    <span key={j} className="reaction" title={r.users.join(", ")}>
                      {r.url ? <img className="emoji-img" src={r.url} alt={r.emoji}
                        onError={(e) => e.currentTarget.replaceWith(r.emoji)} /> : r.emoji}
                      <b>{r.count}</b>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </li>
        ))}
      </ol>
      {tr.messages.some((m) => m.attachments.length > 0) && <p className="muted small">{t("transcript.link_expiry")}</p>}
      {tr.notes.length > 0 && (
        <>
          <h3>{t("transcript.notes")}</h3>
          <ul className="notes">
            {tr.notes.map((n, i) => (
              <li key={i}>
                <div className="row"><strong>{n.author}</strong><span className="muted small">{dateTime(n.created_at, lang)}</span></div>
                <p className="prewrap">{n.text}</p>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

export function DeleteTicket({ guildId, ticketId }: { guildId: string; ticketId: number }) {
  const { t } = useI18n();
  const run = useRun(guildId);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  async function remove() {
    if (!window.confirm(t("ticket.delete_confirm"))) return;
    setBusy(true);
    const ok = await run(() => api(`/guilds/${guildId}/tickets/${ticketId}`, { method: "DELETE" }));
    setBusy(false);
    if (ok) {
      queryClient.invalidateQueries({ queryKey: ["tickets", guildId] });
      queryClient.invalidateQueries({ queryKey: ["stats", guildId] });
      navigate(`/servers/${guildId}/tickets?status=closed`);
    }
  }
  return <button className="button button-danger" disabled={busy} onClick={remove}>{t("ticket.delete")}</button>;
}
