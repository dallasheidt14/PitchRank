type RawGa4 = {
  dimensionHeaders?: { name: string }[];
  metricHeaders?: { name: string }[];
  rows?: { dimensionValues?: { value: string }[]; metricValues?: { value: string }[] }[];
};

export function ga4RowsToObjects(raw: RawGa4): Record<string, string | number>[] {
  if (!raw.rows?.length) return [];
  const dimNames = (raw.dimensionHeaders ?? []).map((h) => h.name);
  const metricNames = (raw.metricHeaders ?? []).map((h) => h.name);
  return raw.rows.map((row) => {
    const obj: Record<string, string | number> = {};
    (row.dimensionValues ?? []).forEach((v, i) => {
      obj[dimNames[i]] = v.value;
    });
    (row.metricValues ?? []).forEach((v, i) => {
      const num = Number(v.value);
      obj[metricNames[i]] = Number.isNaN(num) ? v.value : num;
    });
    return obj;
  });
}
