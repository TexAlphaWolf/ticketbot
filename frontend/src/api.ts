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
  escalation_levels: number;
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
  has_transcript: boolean;
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

// ------------------------------------------------------------- actions ---

export interface Queued {
  command_id: number;
  status: string;
}

export interface CommandStatus {
  id: number;
  kind: string;
  status: "pending" | "running" | "done" | "failed";
  result: string | null;
}

export interface StaffMember extends Person {
  id: string;
}

/** Wait for the bot to carry out a queued action (it checks every few seconds). */
export async function waitForCommand(guildId: string, queued: Queued, timeoutMs = 45_000) {
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) {
    await new Promise((r) => setTimeout(r, 1500));
    const c = await api<CommandStatus>(`/guilds/${guildId}/commands/${queued.command_id}`);
    if (c.status === "done") return c;
    if (c.status === "failed") throw new ApiError(409, c.result ?? "failed");
  }
  throw new ApiError(504, "timeout");
}

// ---------------------------------------------------------- statistics ---

export interface Stats {
  period: "7" | "30" | "90" | "all";
  opened: number;
  closed: number;
  open: number;
  unclaimed: number;
  avg_first_response: number | null;
  avg_resolution: number | null;
  avg_rating: number | null;
  ratings: number;
  by_type: Record<string, number>;
  by_priority: Record<string, number>;
  faq_solved: number;
  faq_opened: number;
  leaderboard: { staff_id: string; handled: number; avg_rating: number | null; ratings: number; avg_first_response: number | null }[];
  people: Record<string, Person>;
}

// ------------------------------------------------------------ admin -----

export interface DiscordRole {
  id: string;
  name: string;
  color: number;
  position: number;
  assignable: boolean;
}

export interface Settings {
  language: "en" | "it" | "de";
  retention_days: number;
  staff_reminders: boolean;
  auto_assign: boolean;
  ticket_cooldown: number;
  ticket_mode: "channel" | "thread";
  staff_role: string | null;
}

export interface Question {
  position: number;
  label: string;
  placeholder: string;
  long: boolean;
  required: boolean;
}

export interface AdminType extends TicketType {
  position: number;
  roles: string[];
  questions: Question[];
}

export interface FaqEntry {
  id: number;
  type_key: string | null;
  question: string;
  answer: string;
  created_at: number;
}

export interface Level {
  level: number;
  role_id: string;
  after_hours: number | null;
}

export const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

// ---------------------------------------------------------- transcripts ---

export interface TranscriptMessage {
  author: string;
  author_id: string;
  avatar: string;
  bot: boolean;
  created_at: number;
  content: string;
  attachments: { filename: string; url: string; image: boolean }[];
  embeds: { author: string; title: string; description: string; fields: [string, string][]; footer: string }[];
  stickers: { name: string; id: string; url: string; image: boolean }[];
  reactions: { emoji: string; id: string | null; url: string | null; count: number; users: string[] }[];
}

export interface Transcript {
  channel_name: string;
  created_at: number;
  messages: TranscriptMessage[];
  notes: { author: string; author_id: string; text: string; created_at: number }[];
}

// ------------------------------------------------------------- members ---

export interface MemberGuild {
  id: string;
  name: string;
  icon_url: string | null;
}

export interface FormType extends TicketType {
  questions: { label: string; placeholder: string; long: boolean; required: boolean; max_length: number }[];
  faq: { question: string; answer: string }[];
}

export interface MyTicket {
  id: number;
  number: number | null;
  name: string | null;
  type_label: string;
  type_emoji: string;
  subject: string | null;
  status: Status;
  channel_id: string | null;
  opened_at: number;
  closed_at: number | null;
  has_transcript: boolean;
}

export interface MemberGuildDetail extends MemberGuild {
  types: FormType[];
  tickets: MyTicket[];
}

export interface MyCommand {
  status: "pending" | "running" | "done" | "failed";
  result: string | null;
  channel_id: string | null;
}
