import type { WebSource } from "./webTools";

export function sourcesToContext(sources: WebSource[]): string {
  return sources
    .map((s, i) => `[${i + 1}] ${s.title}\nURL: ${s.url}\n${s.snippet}`)
    .join("\n\n");
}

export function dedupeSources(sources: WebSource[]): WebSource[] {
  const seen = new Set<string>();
  const out: WebSource[] = [];
  for (const newSource of sources) {
    const key = newSource.url.replace(/\/$/, "");
    if (key && !seen.has(key)) {
      seen.add(key);
      out.push(newSource);
    }
  }
  return out.slice(0, 8);
}
