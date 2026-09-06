import 'server-only';

/**
 * The timezone the business is operated from, and the one every date on the
 * admin dashboards is bucketed and rendered in.
 *
 * Matches the property timezone the internal-analytics queries already use
 * (`lib/internal-analytics/*`), so "this month" means the same month on the
 * subscriptions dashboard as it does on a GA4 or GSC card.
 *
 * This has to be named explicitly at every boundary. Vercel runs functions with
 * `TZ=UTC`, so a `Date` formatted or bucketed without a zone lands seven hours
 * ahead of the operator reading it: the dashboard rolled over to the next
 * calendar day — and to the next `day N of 30` — at 5pm local, which both
 * misdated the page and cut the month's run rate by a full day's worth of
 * denominator while signups were still arriving.
 */
export const BUSINESS_TIMEZONE = 'America/Phoenix';

const WALL_CLOCK = new Intl.DateTimeFormat('en-US', {
  timeZone: BUSINESS_TIMEZONE,
  hourCycle: 'h23',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});

export type WallClock = {
  /** Full year, e.g. 2026. */
  year: number;
  /** 1-12, unlike `Date`'s 0-11 — these are read off a formatted string, not a Date. */
  month: number;
  day: number;
};

/** The calendar date showing on a clock in {@link BUSINESS_TIMEZONE} at `instant`. */
export function wallClockDate(instant: Date): WallClock {
  const parts: Record<string, string> = {};
  for (const part of WALL_CLOCK.formatToParts(instant)) {
    if (part.type !== 'literal') parts[part.type] = part.value;
  }
  return {
    year: Number(parts.year),
    month: Number(parts.month),
    day: Number(parts.day),
  };
}

/**
 * Milliseconds to add to a UTC-interpreted wall clock to recover the instant it
 * names in {@link BUSINESS_TIMEZONE} — i.e. the negated UTC offset.
 */
function offsetMs(instant: Date): number {
  const parts: Record<string, string> = {};
  for (const part of WALL_CLOCK.formatToParts(instant)) {
    if (part.type !== 'literal') parts[part.type] = part.value;
  }
  const asIfUtc = Date.UTC(
    Number(parts.year),
    Number(parts.month) - 1,
    Number(parts.day),
    Number(parts.hour),
    Number(parts.minute),
    Number(parts.second)
  );
  return asIfUtc - instant.getTime();
}

/**
 * The instant at which `year-month-01 00:00:00` begins in {@link BUSINESS_TIMEZONE}.
 *
 * `month` is 1-based. The offset is resolved twice because the first pass reads
 * it at the wrong instant whenever a DST transition sits between the guess and
 * the answer; the second pass reads it at the answer itself. Phoenix does not
 * observe DST, so today this converges on the first pass — the refinement is
 * what keeps the helper correct if the constant above ever changes.
 */
export function startOfMonth(year: number, month: number): number {
  const asIfUtc = Date.UTC(year, month - 1, 1);
  let instant = asIfUtc - offsetMs(new Date(asIfUtc));
  instant = asIfUtc - offsetMs(new Date(instant));
  return instant;
}
