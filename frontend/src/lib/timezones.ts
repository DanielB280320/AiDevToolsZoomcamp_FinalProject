/** The browser's IANA time zone, e.g. "Europe/Madrid"; "UTC" when the browser does not say. */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/**
 * IANA zone names to choose from, sorted, always including `current` (a browser can report an
 * alias such as "Asia/Calcutta" that `supportedValuesOf` lists under its canonical name).
 */
export function timeZoneOptions(current: string): string[] {
  let zones: string[];
  try {
    zones = Intl.supportedValuesOf("timeZone");
  } catch {
    zones = [];
  }
  const all = new Set([...zones, "UTC", current]);
  return [...all].filter(Boolean).sort((a, b) => a.localeCompare(b));
}
