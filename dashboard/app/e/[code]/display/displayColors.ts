export const ACCENT_CYAN = '#00f0ff';
export const ACCENT_MAGENTA = '#ff2bd6';
const HEX_COLOR_RE = /^#[0-9a-f]{6}$/i;

export function safeColor(color: string | undefined, fallback: string): string {
  return color && HEX_COLOR_RE.test(color) ? color : fallback;
}

export function withAlpha(hex: string, alpha: number): string {
  if (!hex || hex[0] !== '#') return hex;
  const value = hex.slice(1);
  const red = parseInt(value.substring(0, 2), 16);
  const green = parseInt(value.substring(2, 4), 16);
  const blue = parseInt(value.substring(4, 6), 16);
  return `rgba(${red},${green},${blue},${alpha})`;
}
