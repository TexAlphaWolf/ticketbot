import type { Lang, T } from "./i18n";

const LOCALES: Record<Lang, string> = { en: "en-GB", it: "it-IT", de: "de-DE" };

export function dateTime(seconds: number, lang: Lang) {
  return new Intl.DateTimeFormat(LOCALES[lang], { dateStyle: "medium", timeStyle: "short" })
    .format(new Date(seconds * 1000));
}

export function duration(seconds: number) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ${m % 60}m`;
  return `${Math.floor(h / 24)}d ${h % 24}h`;
}

export function ago(seconds: number, t: T) {
  const diff = Date.now() / 1000 - seconds;
  return diff < 60 ? t("time.now") : t("time.ago", { t: duration(diff) });
}
