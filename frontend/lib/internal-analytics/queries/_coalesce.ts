const inFlight = new Map<string, Promise<unknown>>();

export function coalesce<T>(key: string, fn: () => Promise<T>): Promise<T> {
  const existing = inFlight.get(key) as Promise<T> | undefined;
  if (existing) return existing;
  const p = fn().finally(() => {
    inFlight.delete(key);
  });
  inFlight.set(key, p);
  return p;
}

export function sortedKeys(obj: unknown): string {
  if (obj === null || typeof obj !== 'object') return JSON.stringify(obj);
  if (Array.isArray(obj)) {
    return JSON.stringify(
      obj.map((v) => (v === undefined ? null : JSON.parse(sortedKeys(v)))),
    );
  }
  const sorted: Record<string, unknown> = {};
  for (const k of Object.keys(obj as object).sort()) {
    const v = (obj as Record<string, unknown>)[k];
    if (v === undefined) continue;
    sorted[k] = JSON.parse(sortedKeys(v));
  }
  return JSON.stringify(sorted);
}
