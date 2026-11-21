import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { api, type Person, type TicketPage } from "../api";
import { Avatar, ErrorBox, Loading, PriorityLabel, StatusBadge } from "../components/ui";
import { ago } from "../format";
import { useI18n } from "../i18n";
import { useGuild } from "./Overview";

const STATUSES = ["open", "closed", "all"] as const;
type Filter = (typeof STATUSES)[number];
const PRIORITIES = ["high", "medium", "low", "none"] as const;
// Filters kept in the address, so a search can be bookmarked and Back works
const KEYS = ["q", "type", "priority", "person", "from", "to"] as const;

export function ticketTitle(t: { number: number | null; name: string | null; id: number }) {
  return t.name ?? `#${t.number ?? t.id}`;
}

/** yyyy-mm-dd (local day) ↔ Unix seconds at the start of that day. */
function dayToSeconds(day: string, endOfDay = false) {
  const [y, m, d] = day.split("-").map(Number);
  return Math.floor(new Date(y, m - 1, d + (endOfDay ? 1 : 0)).getTime() / 1000);
}

function PersonFilter({ id, people, onPick }: { id: string | null; people: Record<string, Person>; onPick: (id: string) => void }) {
  const { t } = useI18n();
  if (!id) return <span className="muted">{t("ticket.unclaimed")}</span>;
  const person = people[id];
  const name = person?.name ?? `#${id.slice(-4)}`;
  return (
    <button type="button" className="person person-link" title={t("tickets.filter.person_hint")} onClick={() => onPick(id)}>
      <Avatar src={person?.avatar_url} name={name} size={20} />
      {name}
    </button>
  );
}

export function Tickets() {
  const { t } = useI18n();
  const { guildId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const status = (STATUSES.find((s) => s === params.get("status")) ?? "open") as Filter;
  const filters = Object.fromEntries(KEYS.map((k) => [k, params.get(k) ?? ""])) as Record<(typeof KEYS)[number], string>;
  const guild = useGuild(guildId);
  const [text, setText] = useState(filters.q);
  const [names, setNames] = useState<Record<string, string>>({});

  function setFilter(name: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: name === "q" });
  }

  // Search while typing, a moment after the last key
  useEffect(() => {
    const timer = setTimeout(() => { if (text.trim() !== filters.q) setFilter("q", text.trim()); }, 350);
    return () => clearTimeout(timer);
  }, [text]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setText(filters.q), [filters.q]);

  const pages = useInfiniteQuery({
    queryKey: ["tickets", guildId, status, filters],
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) => {
      const q = new URLSearchParams({ status, limit: "50" });
      if (filters.q) q.set("q", filters.q);
      if (filters.type) q.set("type", filters.type);
      if (filters.priority) q.set("priority", filters.priority);
      if (filters.person) q.set("person", filters.person);
      if (filters.from) q.set("from", String(dayToSeconds(filters.from)));
      if (filters.to) q.set("to", String(dayToSeconds(filters.to, true)));
      if (pageParam) q.set("before", String(pageParam));
      return api<TicketPage>(`/guilds/${guildId}/tickets?${q}`);
    },
    getNextPageParam: (last) => last.next_before,
  });

  const tickets = pages.data?.pages.flatMap((p) => p.tickets) ?? [];
  const people: Record<string, Person> = Object.assign({}, ...(pages.data?.pages.map((p) => p.people) ?? []));
  const active = KEYS.some((k) => filters[k]);
  const personName = filters.person ? (people[filters.person]?.name ?? names[filters.person] ?? `#${filters.person.slice(-4)}`) : "";

  function pickPerson(id: string) {
    if (people[id]) setNames({ ...names, [id]: people[id].name });
    setFilter("person", id);
  }

  return (
    <>
      <h1>{t("tickets.title")}</h1>
      <div className="search">
        <input type="search" value={text} onChange={(e) => setText(e.target.value)} maxLength={100}
          placeholder={t("tickets.search")} aria-label={t("tickets.search")} />
      </div>
      <div className="filters">
        <div className="segmented" role="group" aria-label={t("tickets.filter.status")}>
          {STATUSES.map((s) => (
            <button key={s} className={s === status ? "active" : ""} onClick={() => setFilter("status", s)}>
              {t(`status.${s}`)}
            </button>
          ))}
        </div>
        <select value={filters.type} onChange={(e) => setFilter("type", e.target.value)} aria-label={t("tickets.filter.type")}>
          <option value="">{t("tickets.filter.all_types")}</option>
          {guild.data?.types.map((ty) => <option key={ty.key} value={ty.key}>{ty.label}</option>)}
        </select>
        <select value={filters.priority} onChange={(e) => setFilter("priority", e.target.value)} aria-label={t("tickets.filter.priority")}>
          <option value="">{t("tickets.filter.any_priority")}</option>
          {PRIORITIES.map((p) => <option key={p} value={p}>{t(`priority.${p}`)}</option>)}
        </select>
        <label className="dates">
          <span>{t("tickets.filter.from")}</span>
          <input type="date" value={filters.from} max={filters.to || undefined} onChange={(e) => setFilter("from", e.target.value)} />
          <span>{t("tickets.filter.to")}</span>
          <input type="date" value={filters.to} min={filters.from || undefined} onChange={(e) => setFilter("to", e.target.value)} />
        </label>
      </div>
      {active && (
        <div className="row active-filters">
          {filters.person && (
            <span className="chip">{t("tickets.filter.person", { name: personName })}
              <button aria-label={t("tickets.remove_filter")} onClick={() => setFilter("person", "")}>×</button>
            </span>
          )}
          <button className="button button-ghost" onClick={() => { setText(""); setParams(status === "open" ? {} : { status }); }}>
            {t("tickets.filter.clear")}
          </button>
        </div>
      )}
      {pages.isPending ? (
        <Loading />
      ) : pages.isError ? (
        <ErrorBox error={pages.error} retry={() => pages.refetch()} />
      ) : tickets.length === 0 && !pages.hasNextPage ? (
        <p className="card muted">{t("tickets.none")}</p>
      ) : (
        <div className="card table-card">
          {tickets.length > 0 && (
            <table className="tickets">
              <thead>
                <tr>
                  <th>{t("tickets.col.ticket")}</th>
                  <th>{t("tickets.col.owner")}</th>
                  <th>{t("tickets.col.staff")}</th>
                  <th>{t("tickets.col.status")}</th>
                  <th>{t("tickets.col.activity")}</th>
                </tr>
              </thead>
              <tbody>
                {tickets.map((ticket) => (
                  <tr key={ticket.id}>
                    <td>
                      <Link to={`/servers/${guildId}/tickets/${ticket.id}`} className="ticket-link">
                        <span className="emoji">{ticket.type_emoji.startsWith("<") ? "🎫" : ticket.type_emoji}</span>
                        <span>
                          <strong>{ticketTitle(ticket)}</strong>
                          <span className="muted small block">{ticket.subject ?? ticket.type_label}</span>
                        </span>
                      </Link>
                    </td>
                    <td><PersonFilter id={ticket.owner_id} people={people} onPick={pickPerson} /></td>
                    <td><PersonFilter id={ticket.claimed_by ?? ticket.assigned_to} people={people} onPick={pickPerson} /></td>
                    <td>
                      <StatusBadge status={ticket.status} />
                      <span className="block small"><PriorityLabel priority={ticket.priority} /></span>
                    </td>
                    <td className="muted">{ago(ticket.closed_at ?? ticket.last_activity, t)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {pages.hasNextPage && (
            <button className="button" onClick={() => pages.fetchNextPage()} disabled={pages.isFetchingNextPage}>
              {tickets.length === 0 || filters.q ? t("tickets.search_more") : t("tickets.more")}
            </button>
          )}
        </div>
      )}
    </>
  );
}
