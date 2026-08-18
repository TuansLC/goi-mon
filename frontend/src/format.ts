/** Shared formatting helpers for the customer screens. */

/** Format an amount with the restaurant currency ("VND" → "20.000đ"). */
export function formatPrice(amount: number, currency = "VND"): string {
  if (currency === "VND") {
    return amount.toLocaleString("vi-VN") + "đ";
  }
  return amount.toLocaleString() + " " + currency;
}

/** Format an ISO timestamp as local "HH:mm". */
export function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
  });
}
