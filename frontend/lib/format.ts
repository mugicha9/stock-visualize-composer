export function formatNumber(value?: number | null, digits = 0): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("ja-JP", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits
  }).format(value);
}

export function formatPrice(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("ja-JP", {
    maximumFractionDigits: value >= 1000 ? 0 : 2
  }).format(value);
}

export function formatPct(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "-";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function formatConfidence(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "-";
  return `${Math.round(value * 100)}%`;
}
