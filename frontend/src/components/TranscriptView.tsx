import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";
import { api, type Transcript } from "../api";
import { dateTime } from "../format";
import { useI18n } from "../i18n";
import { useRun } from "./toast";
import { Avatar, Card, DiscordText, ErrorBox, Loading } from "./ui";

export function TranscriptView({ guildId, ticketId, available }: { guildId: string; ticketId: number; available: boolean }) {
  const { t, lang } = useI18n();
  const transcript = useQuery({
    queryKey: ["transcript", guildId, ticketId],
    queryFn: () => api<Transcript>(`/guilds/${guildId}/tickets/${ticketId}/transcript`),
    enabled: available,
    staleTime: Infinity,
  });
  if (!available) return <Card title={t("transcript.title")}><p className="muted">{t("transcript.none")}</p></Card>;
  if (transcript.isPending) return <Loading />;
  if (transcript.isError) return <ErrorBox error={transcript.error} retry={() => transcript.refetch()} />;
  const tr = transcript.data;
  return (
    <Card title={`${t("transcript.title")} · #${tr.channel_name}`}
      actions={<a className="button" href={`/api/v1/guilds/${guildId}/tickets/${ticketId}/transcript.html`} download>{t("transcript.download")}</a>}>
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
                  {e.title && <strong className="block">{e.title}</strong>}
                  {e.description && <DiscordText text={e.description} />}
                  {e.fields.map(([name, value], k) => (
                    <div key={k} className="small"><strong>{name}</strong><DiscordText text={value} /></div>
                  ))}
                </div>
              ))}
              {m.attachments.map((a, j) => (
                <a key={j} className="attachment" href={a.url} target="_blank" rel="noreferrer">📎 {a.filename}</a>
              ))}
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
