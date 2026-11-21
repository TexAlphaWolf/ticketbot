// Pages for the server's admins: settings, ticket types, FAQ, escalation levels.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import { useParams } from "react-router";
import { type AdminType, api, type DiscordRole, type FaqEntry, json, type Level, type Settings } from "../api";
import { useRun } from "../components/toast";
import { Card, ErrorBox, Loading } from "../components/ui";
import { LANGS, useI18n } from "../i18n";
import { useGuild } from "./Overview";

function useAdmin<T>(path: string) {
  const { guildId = "" } = useParams();
  const query = useQuery({ queryKey: ["admin", guildId, path], queryFn: () => api<T>(`/guilds/${guildId}${path}`) });
  return { guildId, query };
}

function useRoles(guildId: string) {
  return useQuery({ queryKey: ["roles", guildId], queryFn: () => api<DiscordRole[]>(`/guilds/${guildId}/roles`), staleTime: 60_000 });
}

function AdminOnly({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const { guildId = "" } = useParams();
  const guild = useGuild(guildId);
  if (guild.data && guild.data.role !== "admin") return <p className="card muted">{t("admin.only")}</p>;
  return <>{children}</>;
}

function RoleName({ id, roles }: { id: string; roles?: DiscordRole[] }) {
  const role = roles?.find((r) => r.id === id);
  const color = role?.color ? `#${role.color.toString(16).padStart(6, "0")}` : undefined;
  return <span className="role" style={{ color }}>@{role?.name ?? id}</span>;
}

function RolePicker({ roles, exclude, onPick, busy, label }: {
  roles?: DiscordRole[]; exclude: string[]; onPick: (id: string) => void; busy: boolean; label?: string;
}) {
  const { t } = useI18n();
  const [value, setValue] = useState("");
  return (
    <div className="row">
      <select value={value} onChange={(e) => setValue(e.target.value)}>
        <option value="">{t("admin.choose_role")}</option>
        {roles?.filter((r) => r.assignable && !exclude.includes(r.id)).map((r) => <option key={r.id} value={r.id}>@{r.name}</option>)}
      </select>
      <button type="button" className="button" disabled={busy || !value} onClick={() => { onPick(value); setValue(""); }}>
        {label ?? t("types.add_role")}
      </button>
    </div>
  );
}

function useMutate(guildId: string, keys: unknown[][]) {
  const run = useRun(guildId);
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  async function mutate(method: string, path: string, body?: unknown) {
    setBusy(true);
    const ok = await run(
      () => api(`/guilds/${guildId}${path}`, { method, ...(body === undefined ? {} : json(body)) }),
      () => keys.forEach((queryKey) => queryClient.invalidateQueries({ queryKey })),
    );
    setBusy(false);
    return ok;
  }
  return { busy, mutate };
}

// ------------------------------------------------------------- settings ---

export function SettingsPage() {
  const { t } = useI18n();
  const { guildId, query } = useAdmin<Settings>("/settings");
  const { busy, mutate } = useMutate(guildId, [["admin", guildId], ["guild", guildId]]);
  const [form, setForm] = useState<Settings | null>(null);
  useEffect(() => { if (query.data) setForm(query.data); }, [query.data]);
  if (query.isPending || !form) return <AdminOnly><Loading /></AdminOnly>;
  if (query.isError) return <ErrorBox error={query.error} />;
  const set = <K extends keyof Settings>(key: K, value: Settings[K]) => setForm({ ...form, [key]: value });

  function save(e: FormEvent) {
    e.preventDefault();
    const { ticket_mode: _mode, staff_role: _role, ...changes } = form!;
    mutate("PATCH", "/settings", changes);
  }

  return (
    <AdminOnly>
      <h1>{t("nav.settings")}</h1>
      <Card>
        <form onSubmit={save} className="stack form">
          <label className="field"><span>{t("settings.language")}</span>
            <select value={form.language} onChange={(e) => set("language", e.target.value as Settings["language"])}>
              {Object.entries(LANGS).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
            </select>
          </label>
          <label className="field"><span>{t("settings.retention")}</span>
            <input type="number" min={1} max={365} value={form.retention_days} onChange={(e) => set("retention_days", Number(e.target.value))} />
          </label>
          <label className="field"><span>{t("settings.cooldown")}</span>
            <input type="number" min={0} max={1440} value={form.ticket_cooldown} onChange={(e) => set("ticket_cooldown", Number(e.target.value))} />
          </label>
          <label className="check"><input type="checkbox" checked={form.staff_reminders} onChange={(e) => set("staff_reminders", e.target.checked)} /> {t("settings.reminders")}</label>
          <label className="check"><input type="checkbox" checked={form.auto_assign} onChange={(e) => set("auto_assign", e.target.checked)} /> {t("settings.auto_assign")}</label>
          <div><button className="button button-primary" disabled={busy}>{t("settings.save")}</button></div>
        </form>
      </Card>
      <Card title={t("settings.mode")}>
        <div className="stack">
          <div className="segmented">
            {(["channel", "thread"] as const).map((mode) => (
              <button key={mode} className={mode === query.data.ticket_mode ? "active" : ""} disabled={busy || mode === query.data.ticket_mode}
                onClick={() => mutate("PUT", "/settings/mode", { mode })}>{t(`mode.${mode}`)}</button>
            ))}
          </div>
          <p className="muted small">{t("settings.mode_hint")}</p>
        </div>
      </Card>
    </AdminOnly>
  );
}

// ---------------------------------------------------------------- types ---

function TypeCard({ type, roles, guildId }: { type: AdminType; roles?: DiscordRole[]; guildId: string }) {
  const { t } = useI18n();
  const { busy, mutate } = useMutate(guildId, [["admin", guildId], ["guild", guildId]]);
  const [editing, setEditing] = useState(false);
  const [edit, setEdit] = useState({ label: type.label, emoji: type.emoji, description: type.description });
  const [q, setQ] = useState({ label: "", placeholder: "", long: false, required: true });
  const path = `/types/${encodeURIComponent(type.key)}`;

  return (
    <Card title={<>{type.emoji.startsWith("<") ? "🎫" : type.emoji} {type.label} <code className="muted small">{type.key}</code></>}
      actions={<div className="row">
        <button className="button button-ghost" onClick={() => setEditing(!editing)}>{t("types.edit")}</button>
        <button className="button button-ghost danger" disabled={busy}
          onClick={() => window.confirm(t("types.delete_confirm")) && mutate("DELETE", path)}>{t("types.delete")}</button>
      </div>}>
      {type.description && !editing && <p className="muted">{type.description}</p>}
      {editing && (
        <form className="grid-form" onSubmit={async (e) => { e.preventDefault(); if (await mutate("PATCH", path, edit)) setEditing(false); }}>
          <input aria-label={t("types.name")} value={edit.label} maxLength={80} required onChange={(e) => setEdit({ ...edit, label: e.target.value })} />
          <input aria-label={t("types.emoji")} value={edit.emoji} maxLength={64} required className="narrow" onChange={(e) => setEdit({ ...edit, emoji: e.target.value })} />
          <input aria-label={t("types.description")} value={edit.description} maxLength={100} onChange={(e) => setEdit({ ...edit, description: e.target.value })} />
          <button className="button button-primary" disabled={busy}>{t("settings.save")}</button>
        </form>
      )}
      <h3>{t("types.roles")}</h3>
      <div className="row">
        {type.roles.length === 0 && <span className="muted">{t("types.roles_staff")}</span>}
        {type.roles.map((id) => (
          <span key={id} className="chip"><RoleName id={id} roles={roles} />
            <button aria-label={t("types.delete")} disabled={busy} onClick={() => mutate("DELETE", `${path}/roles/${id}`)}>×</button>
          </span>
        ))}
      </div>
      <RolePicker roles={roles} exclude={type.roles} busy={busy} onPick={(role_id) => mutate("POST", `${path}/roles`, { role_id })} />
      <h3>{t("types.questions")}</h3>
      {type.questions.length === 0 && <p className="muted">{t("types.no_questions")}</p>}
      <ol className="questions">
        {type.questions.map((qq) => (
          <li key={qq.position}>
            <strong>{qq.label}</strong>{" "}
            <span className="muted small">{qq.long ? t("types.long") : ""} {qq.required ? `· ${t("types.required")}` : ""}</span>
            {qq.placeholder && <span className="block muted small">{qq.placeholder}</span>}
            <button className="button button-ghost danger small" disabled={busy} onClick={() => mutate("DELETE", `${path}/questions/${qq.position}`)}>{t("types.delete")}</button>
          </li>
        ))}
      </ol>
      {type.questions.length < 3 && (
        <form className="grid-form question-form" onSubmit={async (e) => { e.preventDefault(); if (await mutate("POST", `${path}/questions`, q)) setQ({ label: "", placeholder: "", long: false, required: true }); }}>
          <input placeholder={t("types.question")} value={q.label} maxLength={45} required onChange={(e) => setQ({ ...q, label: e.target.value })} />
          <input placeholder={t("types.example")} value={q.placeholder} maxLength={100} onChange={(e) => setQ({ ...q, placeholder: e.target.value })} />
          <label className="check"><input type="checkbox" checked={q.long} onChange={(e) => setQ({ ...q, long: e.target.checked })} /> {t("types.long")}</label>
          <label className="check"><input type="checkbox" checked={q.required} onChange={(e) => setQ({ ...q, required: e.target.checked })} /> {t("types.required")}</label>
          <button className="button" disabled={busy}>+</button>
        </form>
      )}
    </Card>
  );
}

export function TypesPage() {
  const { t } = useI18n();
  const { guildId, query } = useAdmin<AdminType[]>("/types");
  const roles = useRoles(guildId);
  const { busy, mutate } = useMutate(guildId, [["admin", guildId], ["guild", guildId]]);
  const [form, setForm] = useState({ label: "", emoji: "", description: "" });
  return (
    <AdminOnly>
      <h1>{t("nav.types")}</h1>
      {query.isPending ? <Loading /> : query.isError ? <ErrorBox error={query.error} /> : (
        <>
          {query.data.map((type) => <TypeCard key={type.key} type={type} roles={roles.data} guildId={guildId} />)}
          <Card title={t("types.add")}>
            <form className="grid-form" onSubmit={async (e) => { e.preventDefault(); if (await mutate("POST", "/types", form)) setForm({ label: "", emoji: "", description: "" }); }}>
              <input placeholder={t("types.name")} value={form.label} maxLength={80} required onChange={(e) => setForm({ ...form, label: e.target.value })} />
              <input placeholder={t("types.emoji")} value={form.emoji} maxLength={64} required className="narrow" onChange={(e) => setForm({ ...form, emoji: e.target.value })} />
              <input placeholder={t("types.description")} value={form.description} maxLength={100} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              <button className="button button-primary" disabled={busy}>{t("types.add")}</button>
            </form>
          </Card>
        </>
      )}
    </AdminOnly>
  );
}

// ------------------------------------------------------------------ FAQ ---

function FaqCard({ entry, guildId, typeName }: { entry: FaqEntry; guildId: string; typeName: string }) {
  const { t } = useI18n();
  const { busy, mutate } = useMutate(guildId, [["admin", guildId]]);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ question: entry.question, answer: entry.answer });
  return (
    <Card title={<>#{entry.id} {entry.question}</>} actions={<div className="row">
      <span className="muted small">{typeName}</span>
      <button className="button button-ghost" onClick={() => setEditing(!editing)}>{t("types.edit")}</button>
      <button className="button button-ghost danger" disabled={busy} onClick={() => mutate("DELETE", `/faq/${entry.id}`)}>{t("types.delete")}</button>
    </div>}>
      {editing ? (
        <form className="stack" onSubmit={async (e) => { e.preventDefault(); if (await mutate("PUT", `/faq/${entry.id}`, form)) setEditing(false); }}>
          <input value={form.question} maxLength={100} required onChange={(e) => setForm({ ...form, question: e.target.value })} />
          <textarea value={form.answer} maxLength={1000} rows={4} required onChange={(e) => setForm({ ...form, answer: e.target.value })} />
          <div><button className="button button-primary" disabled={busy}>{t("settings.save")}</button></div>
        </form>
      ) : <p className="prewrap">{entry.answer}</p>}
    </Card>
  );
}

export function FaqPage() {
  const { t } = useI18n();
  const { guildId, query } = useAdmin<FaqEntry[]>("/faq");
  const guild = useGuild(guildId);
  const { busy, mutate } = useMutate(guildId, [["admin", guildId]]);
  const [form, setForm] = useState({ type_key: "", question: "", answer: "" });
  const typeName = (key: string | null) => {
    const type = guild.data?.types.find((ty) => ty.key === key);
    return type ? type.label : t("faq.all_types");
  };
  return (
    <AdminOnly>
      <h1>{t("nav.faq")}</h1>
      {query.isPending ? <Loading /> : query.isError ? <ErrorBox error={query.error} /> : (
        <>
          {query.data.length === 0 && <p className="card muted">{t("faq.none")}</p>}
          {query.data.map((entry) => <FaqCard key={entry.id} entry={entry} guildId={guildId} typeName={typeName(entry.type_key)} />)}
          <Card title={t("faq.add")}>
            <form className="stack" onSubmit={async (e) => {
              e.preventDefault();
              if (await mutate("POST", "/faq", { ...form, type_key: form.type_key || null })) setForm({ type_key: "", question: "", answer: "" });
            }}>
              <label className="field"><span>{t("faq.type")}</span>
                <select value={form.type_key} onChange={(e) => setForm({ ...form, type_key: e.target.value })}>
                  <option value="">{t("faq.all_types")}</option>
                  {guild.data?.types.map((ty) => <option key={ty.key} value={ty.key}>{ty.label}</option>)}
                </select>
              </label>
              <label className="field"><span>{t("faq.question")}</span>
                <input value={form.question} maxLength={100} required onChange={(e) => setForm({ ...form, question: e.target.value })} />
              </label>
              <label className="field"><span>{t("faq.answer")}</span>
                <textarea value={form.answer} maxLength={1000} rows={4} required onChange={(e) => setForm({ ...form, answer: e.target.value })} />
              </label>
              <div><button className="button button-primary" disabled={busy}>{t("faq.add")}</button></div>
            </form>
          </Card>
        </>
      )}
    </AdminOnly>
  );
}

// ----------------------------------------------------------- escalation ---

export function EscalationPage() {
  const { t } = useI18n();
  const { guildId, query } = useAdmin<Level[]>("/escalation");
  const roles = useRoles(guildId);
  const { busy, mutate } = useMutate(guildId, [["admin", guildId], ["guild", guildId]]);
  const [hours, setHours] = useState("");
  return (
    <AdminOnly>
      <h1>{t("nav.escalation")}</h1>
      {query.isPending ? <Loading /> : query.isError ? <ErrorBox error={query.error} /> : (
        <>
          <Card>
            {query.data.length === 0 ? <p className="muted">{t("esc.none")}</p> : (
              <ol className="levels">
                {query.data.map((lv) => (
                  <li key={lv.level}>
                    <strong>{t("esc.level", { n: lv.level })}</strong> · <RoleName id={lv.role_id} roles={roles.data} />
                    <span className="muted small"> · {lv.after_hours ? t("esc.auto", { h: lv.after_hours }) : t("esc.manual")}</span>
                    <button className="button button-ghost danger small" disabled={busy} onClick={() => mutate("DELETE", `/escalation/${lv.level}`)}>{t("types.delete")}</button>
                  </li>
                ))}
              </ol>
            )}
          </Card>
          {query.data.length < 5 && (
            <Card title={t("esc.add")}>
              <div className="stack">
                <label className="field"><span>{t("esc.after")}</span>
                  <input type="number" min={0.5} max={720} step={0.5} value={hours} onChange={(e) => setHours(e.target.value)} />
                </label>
                <RolePicker roles={roles.data} exclude={query.data.map((lv) => lv.role_id)} busy={busy}
                  label={t("esc.level", { n: query.data.length + 1 })}
                  onPick={async (role_id) => { if (await mutate("POST", "/escalation", { role_id, after_hours: hours ? Number(hours) : null })) setHours(""); }} />
              </div>
            </Card>
          )}
        </>
      )}
    </AdminOnly>
  );
}
