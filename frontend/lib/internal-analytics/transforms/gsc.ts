import { pctDelta } from './trend';

type RawGscRow = {
  keys?: string[];
  clicks: number;
  impressions: number;
  ctr: number;
  position: number;
};

export function gscRowsToObjects(raw: { rows?: RawGscRow[] }, dimensions: string[]): Record<string, string | number>[] {
  if (!raw.rows?.length) return [];
  return raw.rows.map((r) => {
    const obj: Record<string, string | number> = {
      clicks: r.clicks,
      impressions: r.impressions,
      ctr: r.ctr,
      position: r.position,
    };
    (r.keys ?? []).forEach((v, i) => {
      obj[dimensions[i]] = v;
    });
    return obj;
  });
}

export function computeGscDeltas(
  current: { clicks: number; impressions: number; ctr: number; position: number },
  previous: { clicks: number; impressions: number; ctr: number; position: number }
) {
  return {
    clicks_delta: pctDelta(current.clicks, previous.clicks),
    impressions_delta: pctDelta(current.impressions, previous.impressions),
    ctr_delta: current.ctr - previous.ctr,
    position_delta: previous.position - current.position, // lower is better → positive = improvement
  };
}
