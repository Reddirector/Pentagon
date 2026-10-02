"use node";

import { v } from "convex/values";
import { action } from "./_generated/server";

/**
 * get_current_time — deterministic clock tool. NO web calls.
 *
 * Node has the full IANA tz database built in, which is the equivalent of
 * Python's `zoneinfo.ZoneInfo`: given an IANA timezone id we can produce the
 * exact local wall-clock time, UTC offset and zone name with zero network
 * requests.
 *
 * The frontend sends the browser's IANA zone
 * (Intl.DateTimeFormat().resolvedOptions().timeZone) on every request; if it
 * is missing or unknown we fall back to Asia/Kolkata.
 */

export const DEFAULT_TZ = "Asia/Kolkata";

/** Small place-name → IANA zone map for "time in <place>" queries. */
const PLACE_TO_TZ: Record<string, string> = {
  india: "Asia/Kolkata",
  "new delhi": "Asia/Kolkata",
  delhi: "Asia/Kolkata",
  mumbai: "Asia/Kolkata",
  bangalore: "Asia/Kolkata",
  bengaluru: "Asia/Kolkata",
  chennai: "Asia/Kolkata",
  kolkata: "Asia/Kolkata",
  hyderabad: "Asia/Kolkata",
  pakistan: "Asia/Karachi",
  karachi: "Asia/Karachi",
  bangladesh: "Asia/Dhaka",
  "sri lanka": "Asia/Colombo",
  nepal: "Asia/Kathmandu",
  china: "Asia/Shanghai",
  beijing: "Asia/Shanghai",
  shanghai: "Asia/Shanghai",
  japan: "Asia/Tokyo",
  tokyo: "Asia/Tokyo",
  osaka: "Asia/Tokyo",
  korea: "Asia/Seoul",
  "south korea": "Asia/Seoul",
  seoul: "Asia/Seoul",
  singapore: "Asia/Singapore",
  malaysia: "Asia/Kuala_Lumpur",
  "kuala lumpur": "Asia/Kuala_Lumpur",
  indonesia: "Asia/Jakarta",
  jakarta: "Asia/Jakarta",
  thailand: "Asia/Bangkok",
  bangkok: "Asia/Bangkok",
  vietnam: "Asia/Ho_Chi_Minh",
  dubai: "Asia/Dubai",
  uae: "Asia/Dubai",
  qatar: "Asia/Qatar",
  "saudi arabia": "Asia/Riyadh",
  riyadh: "Asia/Riyadh",
  israel: "Asia/Jerusalem",
  turkey: "Europe/Istanbul",
  istanbul: "Europe/Istanbul",
  russia: "Europe/Moscow",
  moscow: "Europe/Moscow",
  germany: "Europe/Berlin",
  berlin: "Europe/Berlin",
  france: "Europe/Paris",
  paris: "Europe/Paris",
  london: "Europe/London",
  uk: "Europe/London",
  "united kingdom": "Europe/London",
  britain: "Europe/London",
  england: "Europe/London",
  ireland: "Europe/Dublin",
  netherlands: "Europe/Amsterdam",
  amsterdam: "Europe/Amsterdam",
  spain: "Europe/Madrid",
  madrid: "Europe/Madrid",
  italy: "Europe/Rome",
  rome: "Europe/Rome",
  switzerland: "Europe/Zurich",
  zurich: "Europe/Zurich",
  sweden: "Europe/Stockholm",
  stockholm: "Europe/Stockholm",
  norway: "Europe/Oslo",
  oslo: "Europe/Oslo",
  greece: "Europe/Athens",
  athens: "Europe/Athens",
  poland: "Europe/Warsaw",
  warsaw: "Europe/Warsaw",
  ukraine: "Europe/Kyiv",
  kyiv: "Europe/Kyiv",
  "new york": "America/New_York",
  nyc: "America/New_York",
  washington: "America/New_York",
  boston: "America/New_York",
  "los angeles": "America/Los_Angeles",
  la: "America/Los_Angeles",
  california: "America/Los_Angeles",
  "san francisco": "America/Los_Angeles",
  seattle: "America/Los_Angeles",
  chicago: "America/Chicago",
  texas: "America/Chicago",
  houston: "America/Chicago",
  austin: "America/Chicago",
  denver: "America/Denver",
  "las vegas": "America/Los_Angeles",
  toronto: "America/Toronto",
  canada: "America/Toronto",
  vancouver: "America/Vancouver",
  mexico: "America/Mexico_City",
  "mexico city": "America/Mexico_City",
  brazil: "America/Sao_Paulo",
  "sao paulo": "America/Sao_Paulo",
  "rio de janeiro": "America/Sao_Paulo",
  argentina: "America/Argentina/Buenos_Aires",
  buenosaires: "America/Argentina/Buenos_Aires",
  chile: "America/Santiago",
  peru: "America/Lima",
  colombia: "America/Bogota",
  "south africa": "Africa/Johannesburg",
  johannesburg: "Africa/Johannesburg",
  egypt: "Africa/Cairo",
  cairo: "Africa/Cairo",
  nigeria: "Africa/Lagos",
  lagos: "Africa/Lagos",
  kenya: "Africa/Nairobi",
  nairobi: "Africa/Nairobi",
  morocco: "Africa/Casablanca",
  australia: "Australia/Sydney",
  sydney: "Australia/Sydney",
  melbourne: "Australia/Melbourne",
  perth: "Australia/Perth",
  "new zealand": "Pacific/Auckland",
  auckland: "Pacific/Auckland",
  utc: "UTC",
  gmt: "UTC",
};

const WEEKDAYS = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

export type TimeInfo = {
  iso: string;
  weekday: string;
  date: string;
  time24: string;
  time12: string;
  utcOffset: string;
  timezone: string;
  zoneName: string;
  unixSeconds: number;
};

function offsetLabel(date: Date, tz: string): string {
  // Extract "+05:30" style offset by formatting the instant in the zone and
  // diffing against UTC parts.
  const dtf = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  const parts = dtf.formatToParts(date);
  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value ?? "0");
  const asUTC = Date.UTC(
    get("year"),
    get("month") - 1,
    get("day"),
    get("hour") % 24,
    get("minute"),
    get("second"),
  );
  const diffMin = Math.round((asUTC - date.getTime()) / 60000);
  const sign = diffMin < 0 ? "-" : "+";
  const abs = Math.abs(diffMin);
  const hh = String(Math.floor(abs / 60)).padStart(2, "0");
  const mm = String(abs % 60).padStart(2, "0");
  return `${sign}${hh}:${mm}`;
}

function partsInZone(date: Date, tz: string) {
  const dtf = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour12: false,
    weekday: "long",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  const parts = dtf.formatToParts(date);
  const get = (t: string) =>
    parts.find((p) => p.type === t)?.value ?? "";
  const hour = Number(get("hour")) % 24;
  return {
    weekday: get("weekday"),
    year: get("year"),
    month: get("month"),
    day: get("day"),
    hour: String(hour).padStart(2, "0"),
    minute: get("minute"),
    second: get("second"),
  };
}

function timeZoneName(tz: string, date: Date): string {
  try {
    const dtf = new Intl.DateTimeFormat("en-US", {
      timeZone: tz,
      timeZoneName: "long",
    });
    const part = dtf.formatToParts(date).find((p) => p.type === "timeZoneName");
    return part?.value ?? tz;
  } catch {
    return tz;
  }
}

/** Validates an IANA zone id via Intl support probe. */
export function isValidTimeZone(tz: string): boolean {
  if (!tz || typeof tz !== "string") return false;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

/** Resolve a free-text place (or explicit zone id) to an IANA timezone. */
export function resolveTimezone(input?: string | null): string {
  if (!input) return DEFAULT_TZ;
  const raw = input.trim();
  if (!raw) return DEFAULT_TZ;
  if (isValidTimeZone(raw)) return raw;
  const key = raw.toLowerCase().replace(/^in\s+/, "").trim();
  if (PLACE_TO_TZ[key]) return PLACE_TO_TZ[key];
  // "time in tokyo japan" → try each word / bigram
  const words = key.split(/\s+/);
  for (let i = words.length - 1; i >= 0; i--) {
    if (PLACE_TO_TZ[words[i]]) return PLACE_TO_TZ[words[i]];
  }
  return DEFAULT_TZ;
}

export function getCurrentTime(tzInput?: string | null): TimeInfo {
  const tz = resolveTimezone(tzInput);
  const now = new Date();
  const p = partsInZone(now, tz);
  return {
    iso: `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:${p.second}`,
    weekday: p.weekday,
    date: `${p.weekday}, ${p.year}-${p.month}-${p.day}`,
    time24: `${p.hour}:${p.minute}:${p.second}`,
    time12: format12(p.hour, p.minute),
    utcOffset: offsetLabel(now, tz),
    timezone: tz,
    zoneName: timeZoneName(tz, now),
    unixSeconds: Math.floor(now.getTime() / 1000),
  };
}

function format12(hour24: string, minute: string): string {
  const h = Number(hour24);
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${minute} ${ampm}`;
}

/** Zone display name (e.g. "India Standard Time") for the current instant. */
export function zoneDisplayName(tz: string): string {
  return timeZoneName(tz, new Date());
}

/** Render a TimeInfo as a compact human/LLM-readable string. */
export function describeTime(info: TimeInfo): string {
  return (
    `${info.iso} ${info.utcOffset}` +
    ` (${info.weekday})` +
    ` — ${info.timezone}`
  );
}

export const WEEKDAY_NAMES = WEEKDAYS;

/**
 * Rule-based router: does this query ask about current time / date / day?
 * Pure regex — no LLM call.
 */
export function isTimeQuery(text: string): boolean {
  if (!text) return false;
  const t = text.toLowerCase().trim();
  // Explicit IANA zone mentions should also route to the clock.
  if (/\b(utc|gmt)\b/.test(t) && /\btime\b/.test(t)) return true;
  return (
    /\b(current|right)?\s*(time|clock)\b/.test(t) ||
    /\b(what|which|whats|what's)\s+(day|date)\b/.test(t) ||
    /\btoday'?s?\s+(date|day)\b/.test(t) ||
    /\b(what|which)\s+day\s+is\s+it\b/.test(t) ||
    /\bis\s+it\s+(am|pm)\b/.test(t) ||
    /\bhow\s+(late|early)\b/.test(t) ||
    /\bdate\s+today\b/.test(t) ||
    /\btime\s+(now|right now|in)\b/.test(t) ||
    /\bnow\b.*\b(time|date|day)\b|\b(time|date|day)\b.*\bnow\b/.test(t) ||
    // "in india right now" style — only when combined with time words above
    /\bright now\b/.test(t) && /\b(time|date|day|today)\b/.test(t) ||
    /\btoday\b/.test(t) && /\b(time|date|day)\b/.test(t)
  );
}

/** Extract "time in <place>" → place string, if present. */
export function extractPlaceFromQuery(text: string): string | null {
  const t = text.toLowerCase().trim();
  const m =
    /\b(?:time|clock)\s+(?:in|at|for)\s+([a-z][a-z\s'-]{1,40})/.exec(t) ||
    /\b(?:in|at)\s+([a-z][a-z\s'-]{1,40}?)\s+(?:right\s+now|now|today)\b/.exec(t) ||
    /\b(?:current\s+time|local\s+time)\s+(?:in|at)\s+([a-z][a-z\s'-]{1,40})/.exec(t);
  if (!m) return null;
  const place = m[1]
    .replace(/\?+$/, "")
    .replace(/\b(right now|now|today|please|currently)\b.*$/, "")
    .trim();
  return place || null;
}

// ---------------------------------------------------------------------------
// Convex action wrapper so the UI can also display the live clock.
// ---------------------------------------------------------------------------

export const getCurrentTimeAction = action({
  args: { timezone: v.optional(v.string()) },
  handler: async (_ctx, { timezone }): Promise<TimeInfo> => {
    return getCurrentTime(timezone ?? null);
  },
});
