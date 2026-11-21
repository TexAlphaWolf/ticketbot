import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { api, json, type Priority, type StaffMember, type TicketDetail } from "../api";
import { useI18n } from "../i18n";
import { useRun } from "./toast";
import { Card } from "./ui";

const PRIORITIES: Priority[] = ["low", "medium", "high"];

export function TicketActions({ guildId, ticket, levels, part }: {
  guildId: string; ticket: TicketDetail; levels: number; part: "main" | "side";
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const run = useRun(guildId);
  const base = `/guilds/${guildId}/tickets/${ticket.id}`;
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState("");
  const [note, setNote] = useState("");
  const [priority, setPriority] = useState<Priority>(ticket.priority ?? "medium");
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [closeReason, setCloseReason] = useState("");
  const [closing, setClosing] = useState(false);
  const staff = useQuery({
    queryKey: ["staff", guildId],
    queryFn: () => api<StaffMember[]>(`/guilds/${guildId}/staff`),
    staleTime: 300_000,
  });

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ["ticket", guildId] });
    queryClient.invalidateQueries({ queryKey: ["tickets", guildId] });
    queryClient.invalidateQueries({ queryKey: ["guild", guildId] });
  }

  async function act(call: () => Promise<unknown>, after?: () => void) {
    setBusy(true);
    const ok = await run(call, refresh);
    setBusy(false);
    if (ok) after?.();
  }

  const post = (path: string, body: unknown) => api(base + path, { method: "POST", ...json(body) });

  function submitReply(e: FormEvent) {
    e.preventDefault();
    act(() => post("/messages", { text: reply }), () => setReply(""));
  }

  function submitNote(e: FormEvent) {
    e.preventDefault();
    act(() => post("/notes", { text: note }), () => setNote(""));
  }

  const others = (staff.data ?? []).filter((s) => s.id !== ticket.claimed_by);
  const atTop = ticket.escalation_level >= levels;

  if (part === "main") return (
    <>
      <Card title={t("action.reply")}>
        <form onSubmit={submitReply} className="stack">
          <textarea value={reply} onChange={(e) => setReply(e.target.value)} rows={4} maxLength={2000} required />
          <div className="row spread">
            <span className="muted small">{t("action.reply_hint")}</span>
            <button className="button button-primary" disabled={busy || !reply.trim()}>{t("action.send")}</button>
          </div>
        </form>
      </Card>
      <Card title={t("action.add_note")}>
        <form onSubmit={submitNote} className="stack">
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={1000} required />
          <div className="row spread">
            <span className="muted small">{t("action.note_hint")}</span>
            <button className="button" disabled={busy || !note.trim()}>{t("action.add_note")}</button>
          </div>
        </form>
      </Card>
    </>
  );

  return (
    <>
      <Card title={t("action.title")}>
        <div className="stack">
          <label className="field">
            <span>{t("action.priority")}</span>
            <div className="row">
              <select value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
                {PRIORITIES.map((p) => <option key={p} value={p}>{t(`priority.${p}`)}</option>)}
              </select>
              {ticket.claimed_by ? (
                <button className="button" disabled={busy || priority === ticket.priority}
                  onClick={() => act(() => post("/priority", { priority }))}>{t("action.apply")}</button>
              ) : (
                <button className="button button-primary" disabled={busy}
                  onClick={() => act(() => post("/claim", { priority }))}>{t("action.claim")}</button>
              )}
            </div>
          </label>
          <label className="field">
            <span>{t("action.transfer")}</span>
            <div className="row">
              <select value={others.some((s) => s.id === target) ? target : ""} onChange={(e) => setTarget(e.target.value)}>
                <option value="">{t("action.transfer_pick")}</option>
                {others.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
              <input inputMode="numeric" pattern="\d{15,20}" placeholder={t("action.transfer_id")}
                value={target} onChange={(e) => setTarget(e.target.value.trim())} />
              <button className="button" disabled={busy || !/^\d{15,20}$/.test(target)}
                onClick={() => act(() => post("/transfer", { member_id: target }), () => setTarget(""))}>
                {t("action.apply")}
              </button>
            </div>
          </label>
          {levels > 0 && (
            <label className="field">
              <span>{t("action.escalate")}</span>
              <div className="row">
                <input placeholder={t("action.reason")} value={reason} maxLength={300}
                  onChange={(e) => setReason(e.target.value)} disabled={atTop} />
                <button className="button" disabled={busy || atTop}
                  onClick={() => act(() => post("/escalate", { reason: reason || null }), () => setReason(""))}>
                  {atTop ? t("action.escalate_top") : `⬆️ ${t("esc.level", { n: ticket.escalation_level + 1 })}`}
                </button>
              </div>
            </label>
          )}
          <div className="danger-zone">
            {closing ? (
              <div className="stack">
                <p>{t("action.close_confirm")}</p>
                <input placeholder={t("action.reason")} value={closeReason} maxLength={500}
                  onChange={(e) => setCloseReason(e.target.value)} />
                <div className="row">
                  <button className="button button-danger" disabled={busy}
                    onClick={() => act(() => post("/close", { reason: closeReason || null }), () => setClosing(false))}>
                    {t("action.confirm")}
                  </button>
                  <button className="button button-ghost" onClick={() => setClosing(false)}>{t("action.cancel")}</button>
                </div>
              </div>
            ) : (
              <button className="button button-danger" onClick={() => setClosing(true)}>{t("action.close")}</button>
            )}
          </div>
        </div>
      </Card>
    </>
  );
}
