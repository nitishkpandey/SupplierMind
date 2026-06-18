const EMPTY_LOCATION_VALUES = new Set([
  "",
  "-",
  "n/a",
  "na",
  "nil",
  "none",
  "null",
  "not applicable",
  "not available",
  "not specified",
  "unknown",
]);

export function cleanLocationPart(value: string | null | undefined): string | null {
  const text = value?.trim();
  if (!text || EMPTY_LOCATION_VALUES.has(text.toLowerCase())) {
    return null;
  }
  return text;
}

export function formatSupplierLocation(
  city: string | null | undefined,
  country: string | null | undefined,
): string | null {
  const parts = [cleanLocationPart(city), cleanLocationPart(country)].filter(Boolean);
  return parts.length > 0 ? parts.join(", ") : null;
}
