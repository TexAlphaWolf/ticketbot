// Typed client of the TicketBot REST API (/api/v1). Cookies carry the login; requests
// that change something also send the CSRF token from /auth/me.

export type Role = "admin" | "staff";

export interface User {
  id: string;
  username: string;
  global_name: string | null;
  avatar_url: string;
}

export interface Me {
  user: User;
  csrf_token: string;
  expires_at: number;
}

export interface GuildSummary {
  id: string;
  name: string;
  icon_url: string | null;
  role: Role;
}

export interface TicketType {
  key: string;
  label: string;
  emoji: string;
  description: string;
}

export interface GuildDetail extends GuildSummary {
  language: string;
  ticket_mode: "channel" | "thread";
  types: TicketType[];
  waiting: number;
  in_progress: number;
  can_see_stats: boolean;
}

export interface Person {
  name: string;
  avatar_url: string;
}

export type Status = "waiting" | "in_progress" | "closed";
export type Priority = "low" | "medium" | "high";

export interface TicketSummary {
  id: number;
  number: number | null;
  name: string | null;
  type_key: string;
  type_label: string;
  type_emoji: string;
  subject: string | null;
  status: Status;
  priority: Priority | null;
  owner_id: string;
  claimed_by: string | null;
  assigned_to: string | null;
  escalation_level: number;
  is_thread: boolean;
  channel_id: string | null;
  opened_at: number;
  last_activity: number;
  closed_at: number | null;
}

export interface TicketPage {
  tickets: TicketSummary[];
  next_before: number | null;
  people: Record<string, Person>;
}

export interface Note {
  author_id: string;
  text: string;
  created_at: number;
}

export interface TicketDetail extends TicketSummary {
  description: string | null;
  first_response_at: number | null;
  closed_by: string | null;
  close_reason: string | null;
  rating: number | null;
  rating_comment: string | null;
  escalated_at: number | null;
  notes: Note[];
  people: Record<string, Person>;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let csrfToken: string | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body !== undefined) headers.set("Content-Type", "application/json");
  if (method !== "GET" && csrfToken) headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch("/api/v1" + path, { ...init, headers, credentials: "same-origin" });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      // not JSON: keep the status text
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function loginUrl(next = window.location.pathname + window.location.search) {
  return "/api/v1/auth/login?next=" + encodeURIComponent(next);
}

export function channelUrl(guildId: string, channelId: string) {
  return `https://discord.com/channels/${guildId}/${channelId}`;
}
