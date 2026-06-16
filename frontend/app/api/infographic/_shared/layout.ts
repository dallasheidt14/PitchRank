// Dynamic sizing for the Instagram (square-by-default) infographics.
//
// The feed image starts square (1080×1080) and grows toward portrait — capped at
// Instagram's 4:5 limit (1080×1350) — only when long team names wrap to a second
// line, so rows are never clipped and names are never truncated. Story and Twitter
// keep their fixed dimensions and are unaffected.

export const IG_MIN_HEIGHT = 1080;
export const IG_MAX_HEIGHT = 1350; // Instagram 4:5 portrait cap

// Oswald is condensed; this is the mean glyph advance as a fraction of the font
// size, tuned against rendered output. Used only to estimate how many lines a
// name will occupy so the canvas can be sized to fit it.
const OSWALD_CHAR_RATIO = 0.52;

export function lineCount(text: string, fontSize: number, maxWidth: number, maxLines = 2): number {
  const charsPerLine = Math.max(1, Math.floor(maxWidth / (fontSize * OSWALD_CHAR_RATIO)));
  const lines = Math.ceil((text?.length ?? 0) / charsPerLine);
  return Math.min(maxLines, Math.max(1, lines));
}

// Clamp a computed content height into Instagram's allowed range.
export function clampIgHeight(contentHeight: number): number {
  return Math.max(IG_MIN_HEIGHT, Math.min(IG_MAX_HEIGHT, Math.round(contentHeight)));
}
