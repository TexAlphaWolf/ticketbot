import { useInfiniteQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router";
import { api, type TicketPage } from "../api";
import { ErrorBox, Loading, PersonChip, PriorityLabel, StatusBadge } from "../components/ui";
import { ago } from "../format";
import { useI18n } from "../i18n";
import { useGuild } from "./Overview";

const STATUSES = ["open", "closed", "all"] as const;
type Filter = (typeof STATUSES)[number];

export function ticketTitle(t: { number: number | null; name: string | null; id: number }) {
  return t.name ?? `#${t.number ?? t.id}`;
}

export function Tickets() {
  const { t } = useI18n();
  const { guildId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const status = (STATUSES.find((s) => s === params.get("status")) ?? "open") as Filter;
  const type = params.get("type") ?? "";
  const guild = useGuild(guildId);

  const pages = useInfiniteQuery({
    queryKey: ["tickets", guildId, status, type],
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) => {
      const q = new URLSearchParams({ status, limit: "50" });
      if (type) q.set("type", type);
      if (pageParam) q.set("before", String(pageParam));
      return api<TicketPage>(`/guilds/${guildId}/tickets?${q}`);
    },
    getNextPageParam: (last) => last.next_before,
  });

  function setFilter(name: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    setParams(next, { replace: true });
  }

  const tickets = pages.data?.pages.flatMap((p) => p.tickets) ?? [];
  const people = Object.assign({}, ...(pages.data?.pages.map((p) => p.people) ?? []));

  return (
    <>
      <h1>{t("tickets.title")}</h1>
      <div className="filters">
        <div className="segmented" role="group" aria-label={t("tickets.filter.status")}>
          {STATUSES.map((s) => (
            <button key={s} className={s === status ? "active" : ""} onClick={() => setFilter("status", s)}>
              {t(`status.${s}`)}
            </button>
          ))}
        </div>
        <label>
          <span className="visually-hidden">{t("tickets.filter.type")}</span>
          <select value={type} onChange={(e) => setFilter("type", e.target.value)}>
            <option value="">{t("tickets.filter.all_types")}</option>
            {guild.data?.types.map((ty) => (
              <option key={ty.key} value={ty.key}>
                {ty.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {pages.isPending ? (
        <Loading />
      ) : pages.isError ? (
        <ErrorBox error={pages.error} retry={() => pages.refetch()} />
      ) : tickets.length === 0 ? (
        <p className="card muted">{t("tickets.none")}</p>
      ) : (
        <div className="card table-card">
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
                  <td>
                    <PersonChip id={ticket.owner_id} people={people} />
                  </td>
                  <td>
                    <PersonChip id={ticket.claimed_by ?? ticket.assigned_to} people={people} />
                  </td>
                  <td>
                    <StatusBadge status={ticket.status} />
                    <span className="block small">
                      <PriorityLabel priority={ticket.priority} />
                    </span>
                  </td>
                  <td className="muted">{ago(ticket.closed_at ?? ticket.last_activity, t)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {pages.hasNextPage && (
            <button className="button" onClick={() => pages.fetchNextPage()} disabled={pages.isFetchingNextPage}>
              {t("tickets.more")}
            </button>
          )}
        </div>
      )}
    </>
  );
}
