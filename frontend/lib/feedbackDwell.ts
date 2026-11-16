/**
 * A feedback report sent sooner than this after its form opened is treated as a bot: the route
 * answers ok and delivers nothing. Kept out of lib/constants.ts, whose exact source the Compare
 * research pins.
 */
export const MIN_FEEDBACK_DWELL_MS = 2000;
