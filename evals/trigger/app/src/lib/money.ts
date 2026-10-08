export function formatPrice(cents: number, currency = "GBP"): string {
  return new Intl.NumberFormat("en-GB", { style: "currency", currency }).format(cents / 100);
}

export function orderTotal(lines: { priceCents: number; quantity: number }[]): number {
  return lines.reduce((total, line) => total + line.priceCents * line.quantity, 0);
}
