// For every member: open a ticket from the browser (FAQ first, then the same form as on
// Discord) and see your own tickets.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link, Navigate, useParams } from "react-router";
import {
  api, ApiError, channelUrl, type FormType, json, type MemberGuild, type MemberGuildDetail,
  type MyCommand, type Queued,
} from "../api";
import { TranscriptView } from "../components/TranscriptView";
import { Avatar, Card, DiscordText, ErrorBox, Loading, StatusBadge } from "../components/ui";
import { dateTime } from "../format";
import { useI18n } from "../i18n";

const emoji = (e: string) => (e.startsWith("<") ? "🎫" : e);

export function OpenChooseServer() {
  const { t } = useI18n();
  const guilds = useQuery({ queryKey: ["me-guilds"], queryFn: () => api<MemberGuild[]>("/me/guilds") });
  if (guilds.isPending) return <Loading />;
  if (guilds.isError) return <ErrorBox error={guilds.error} retry={() => guilds.refetch()} />;
  if (guilds.data.length === 1) return <Navigate to={`/open/${guilds.data[0].id}`} replace />;
  return (
    <>
      <h1>{t("open.title")}</h1>
      {guilds.data.length === 0 ? <p className="card muted">{t("open.no_servers")}</p> : (
        <>
          <p className="muted">{t("open.choose_server")}</p>
          <div className="grid">
            {guilds.data.map((g) => (
              <Link key={g.id} to={`/open/${g.id}`} className="card server-card">
                <Avatar src={g.icon_url} name={g.name} size={48} />
                <strong>{g.name}</strong>
              </Link>
            ))}
          </div>
        </>
      )}
    </>
  );
}

type Step = { kind: "types" } | { kind: "faq"; type: FormType } | { kind: "form"; type: FormType }
  | { kind: "working" } | { kind: "done"; channelId: string } | { kind: "failed"; reason: string } | { kind: "solved" };

async function waitForTicket(guildId: string, queued: Queued): Promise<MyCommand> {
  const until = Date.now() + 45_000;
  while (Date.now() < until) {
    await new Promise((r) => setTimeout(r, 1500));
    const c = await api<MyCommand>(`/me/guilds/${guildId}/commands/${queued.command_id}`);
    if (c.status === "done" || c.status === "failed") return c;
  }
  throw new ApiError(504, "timeout");
}

function TicketForm({ guildId, type, onSent, onBack }: {
  guildId: string; type: FormType; onSent: (q: Queued) => void; onBack: () => void;
}) {
  const { t } = useI18n();
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [answers, setAnswers] = useState<string[]>(type.questions.map(() => ""));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSent(await api<Queued>(`/me/guilds/${guildId}/tickets`, {
        method: "POST", ...json({ type_key: type.key, subject, description, answers }),
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <Card title={<>{emoji(type.emoji)} {type.label}</>} actions={<button className="button button-ghost" onClick={onBack}>{t("open.back")}</button>}>
      <form className="stack form" onSubmit={submit}>
        <label className="field"><span>{t("open.subject")}</span>
          <input value={subject} maxLength={100} required onChange={(e) => setSubject(e.target.value)} />
        </label>
        {type.questions.length === 0 ? (
          <label className="field"><span>{t("open.description")}</span>
            <textarea value={description} maxLength={1000} rows={6} required onChange={(e) => setDescription(e.target.value)} />
          </label>
        ) : type.questions.map((q, i) => (
          <label key={i} className="field">
            <span>{q.label}{!q.required && ` (${t("open.optional")})`}</span>
            {q.long ? (
              <textarea value={answers[i]} maxLength={q.max_length} rows={4} required={q.required} placeholder={q.placeholder}
                onChange={(e) => setAnswers(answers.map((a, j) => (j === i ? e.target.value : a)))} />
            ) : (
              <input value={answers[i]} maxLength={q.max_length} required={q.required} placeholder={q.placeholder}
                onChange={(e) => setAnswers(answers.map((a, j) => (j === i ? e.target.value : a)))} />
            )}
          </label>
        ))}
        <p className="muted small">{t("open.attachments_hint")}</p>
        {error && <p className="notice notice-error" role="alert">{error}</p>}
        <div><button className="button button-primary" disabled={busy}>{t("open.send")}</button></div>
      </form>
    </Card>
  );
}

export function OpenTicket() {
  const { t, lang } = useI18n();
  const { guildId = "" } = useParams();
  const queryClient = useQueryClient();
  const detail = useQuery({ queryKey: ["me-guild", guildId], queryFn: () => api<MemberGuildDetail>(`/me/guilds/${guildId}`) });
  const [step, setStep] = useState<Step>({ kind: "types" });
  const [shown, setShown] = useState<number | null>(null);

  if (detail.isPending) return <Loading />;
  if (detail.isError) return <ErrorBox error={detail.error} retry={() => detail.refetch()} />;
  const g = detail.data;

  async function sent(queued: Queued) {
    setStep({ kind: "working" });
    try {
      const c = await waitForTicket(guildId, queued);
      setStep(c.status === "done" && c.channel_id ? { kind: "done", channelId: c.channel_id } : { kind: "failed", reason: c.result ?? "?" });
    } catch (err) {
      setStep({ kind: "failed", reason: err instanceof ApiError && err.status === 504 ? t("toast.timeout") : String(err) });
    }
    queryClient.invalidateQueries({ queryKey: ["me-guild", guildId] });
  }

  function choose(type: FormType) {
    setStep(type.faq.length ? { kind: "faq", type } : { kind: "form", type });
  }

  async function solved(type: FormType) {
    await api(`/me/guilds/${guildId}/faq`, { method: "POST", ...json({ type_key: type.key, solved: true }) }).catch(() => undefined);
    setStep({ kind: "solved" });
  }

  return (
    <>
      <header className="page-header">
        <Avatar src={g.icon_url} name={g.name} size={48} />
        <h1>{t("open.title")} · {g.name}</h1>
      </header>

      {step.kind === "types" && (
        <Card title={t("open.choose_type")}>
          <div className="type-grid">
            {g.types.map((type) => (
              <button key={type.key} className="type-card" onClick={() => choose(type)}>
                <span className="emoji big">{emoji(type.emoji)}</span>
                <strong>{type.label}</strong>
                {type.description && <span className="muted small">{type.description}</span>}
              </button>
            ))}
          </div>
        </Card>
      )}
      {step.kind === "faq" && (
        <Card title={`💡 ${t("open.faq_title")} · ${step.type.label}`}>
          <p className="muted">{t("open.faq_intro")}</p>
          {step.type.faq.map((f, i) => (
            <details key={i} className="faq" open={i === 0}>
              <summary>{f.question}</summary>
              <DiscordText text={f.answer} />
            </details>
          ))}
          <div className="row">
            <button className="button button-primary" onClick={() => solved(step.type)}>✅ {t("open.solved")}</button>
            <button className="button" onClick={() => setStep({ kind: "form", type: step.type })}>📩 {t("open.anyway")}</button>
          </div>
        </Card>
      )}
      {step.kind === "form" && (
        <TicketForm guildId={guildId} type={step.type} onSent={sent} onBack={() => setStep({ kind: "types" })} />
      )}
      {step.kind === "working" && <Card><div className="loading"><span className="spinner" aria-hidden /> {t("open.working")}</div></Card>}
      {step.kind === "solved" && (
        <Card><p>✅ {t("open.glad")}</p><button className="button" onClick={() => setStep({ kind: "types" })}>{t("open.another")}</button></Card>
      )}
      {step.kind === "done" && (
        <Card>
          <p>✅ {t("open.done")}</p>
          <div className="row">
            <a className="button button-primary" href={channelUrl(guildId, step.channelId)} target="_blank" rel="noreferrer">{t("open.go_discord")}</a>
          </div>
        </Card>
      )}
      {step.kind === "failed" && (
        <Card>
          <p className="notice notice-error" role="alert">{t("open.failed", { reason: step.reason })}</p>
          <button className="button" onClick={() => setStep({ kind: "types" })}>{t("open.another")}</button>
        </Card>
      )}

      <Card title={t("my.title")}>
        {g.tickets.length === 0 ? <p className="muted">{t("my.none")}</p> : (
          <ul className="my-tickets">
            {g.tickets.map((ticket) => (
              <li key={ticket.id}>
                <div className="row">
                  <span className="emoji">{emoji(ticket.type_emoji)}</span>
                  <strong>{ticket.name ?? `#${ticket.number ?? ticket.id}`}</strong>
                  <StatusBadge status={ticket.status} />
                  <span className="muted small">{ticket.subject ?? ticket.type_label} · {dateTime(ticket.opened_at, lang)}</span>
                  <span className="my-actions">
                  {ticket.channel_id && ticket.status !== "closed" && (
                    <a className="button button-ghost" href={channelUrl(guildId, ticket.channel_id)} target="_blank" rel="noreferrer">{t("ticket.open_discord")}</a>
                  )}
                  {ticket.has_transcript && (
                    <button className="button button-ghost" onClick={() => setShown(shown === ticket.id ? null : ticket.id)}>
                      {shown === ticket.id ? t("my.hide_transcript") : t("my.show_transcript")}
                    </button>
                  )}
                  </span>
                </div>
                {shown === ticket.id && <TranscriptView guildId={guildId} ticketId={ticket.id} available mine />}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <MyData guildId={guildId} />
    </>
  );
}

/** Download everything the bot stores about you in this server, or delete it. */
function MyData({ guildId }: { guildId: string }) {
  const { t } = useI18n();
  const [error, setError] = useState<string | null>(null);
  const [deleted, setDeleted] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  async function erase() {
    if (!window.confirm(t("privacy.confirm"))) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ tickets: number }>(`/me/guilds/${guildId}/privacy`, { method: "DELETE" });
      setDeleted(r.tickets);
      setTimeout(() => { window.location.href = "/"; }, 4000);   // logged out: login page
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <Card title={t("privacy.title")}>
      <p className="muted">{t("privacy.text")}</p>
      {deleted !== null ? <p>✅ {t("privacy.deleted", { count: deleted })}</p> : (
        <div className="row">
          <a className="button" href={`/api/v1/me/guilds/${guildId}/privacy`} download>📦 {t("privacy.download")}</a>
          <button className="button button-danger" disabled={busy} onClick={erase}>🗑️ {t("privacy.delete")}</button>
        </div>
      )}
      {error && <p className="notice notice-error" role="alert">{error}</p>}
    </Card>
  );
}
