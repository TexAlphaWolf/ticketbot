import { type ReactNode, useState } from "react";
import { ApiError, type Person, type Priority, type Status } from "../api";
import { useI18n } from "../i18n";

export function Avatar({ src, name, size = 24 }: { src?: string | null; name: string; size?: number }) {
  const [broken, setBroken] = useState(false);
  if (!src || broken) {
    return (
      <span className="avatar avatar-letter" style={{ width: size, height: size }} aria-hidden>
        {name.slice(0, 1).toUpperCase()}
      </span>
    );
  }
  return (
    <img className="avatar" src={src} alt="" width={size} height={size} loading="lazy"
      onError={() => setBroken(true)} />
  );
}

export function PersonChip({ id, people }: { id: string | null; people: Record<string, Person> }) {
  const { t } = useI18n();
  if (!id) return <span className="muted">{t("ticket.unclaimed")}</span>;
  const person = people[id];
  const name = person?.name ?? `#${id.slice(-4)}`;
  return (
    <span className="person" title={id}>
      <Avatar src={person?.avatar_url} name={name} size={20} />
      {name}
    </span>
  );
}

export function StatusBadge({ status }: { status: Status }) {
  const { t } = useI18n();
  const label = status === "closed" ? t("status.closed_one") : t(`status.${status}`);
  return <span className={`badge badge-${status}`}>{label}</span>;
}

const PRIORITY_DOT: Record<Priority, string> = { low: "🟢", medium: "🟡", high: "🔴" };

export function PriorityLabel({ priority }: { priority: Priority | null }) {
  const { t } = useI18n();
  if (!priority) return <span className="muted">{t("priority.none")}</span>;
  return (
    <span className="priority">
      {PRIORITY_DOT[priority]} {t(`priority.${priority}`)}
    </span>
  );
}

export function Loading() {
  const { t } = useI18n();
  return (
    <div className="loading" role="status">
      <span className="spinner" aria-hidden /> {t("loading")}
    </div>
  );
}

export function ErrorBox({ error, retry }: { error: unknown; retry?: () => void }) {
  const { t } = useI18n();
  const notFound = error instanceof ApiError && (error.status === 404 || error.status === 403);
  const message = notFound ? t("error.not_found") : error instanceof Error ? error.message : String(error);
  return (
    <div className="card error" role="alert">
      <strong>{t("error.title")}</strong>
      <p>{message}</p>
      {retry && !notFound && (
        <button className="button" onClick={retry}>
          {t("error.retry")}
        </button>
      )}
    </div>
  );
}

export function Card({ title, children, actions }: { title?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-header">
          {title && <h2>{title}</h2>}
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

/** Text from Discord with **bold** parts (the form answers): shown without any HTML. */
export function DiscordText({ text }: { text: string }) {
  return (
    <p className="prewrap">
      {text.split(/(\*\*[^*\n]+\*\*)/g).map((part, i) =>
        part.startsWith("**") && part.endsWith("**") && part.length > 4
          ? <strong key={i}>{part.slice(2, -2)}</strong>
          : part,
      )}
    </p>
  );
}
