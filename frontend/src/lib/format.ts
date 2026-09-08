export function formatBytes(value: number): string {
  if (!value || value <= 0) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  let v = value;
  let u = 0;
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024;
    u += 1;
  }
  return u === 0 ? `${v} B` : `${v.toFixed(1)} ${units[u]}`;
}

export function extList(extJson?: string | null): string[] {
  if (!extJson) return [];
  try {
    const d = JSON.parse(extJson) as Record<string, number>;
    return Object.entries(d)
      .filter(([, n]) => n > 0)
      .map(([k]) => k.toUpperCase())
      .sort();
  } catch {
    return [];
  }
}

export function initials(name: string): string {
  const parts = name.split(/[\s\-_:]+/).filter(Boolean);
  const two = parts.slice(0, 2).map((p) => p[0] ?? "").join("");
  return (two || name.slice(0, 2)).toUpperCase();
}
