import type {
  QRResolveResponse,
  CreateOrderRequest,
  CreateOrderResponse,
  SessionSnapshot,
  StaffCallResponse,
  StaffCallCooldownResponse,
  SessionItem,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

/**
 * Resolve QR token — returns restaurant, table, and menu data.
 */
export async function resolveQR(qrToken: string): Promise<QRResolveResponse> {
  const res = await fetch(`${BASE_URL}/t/${qrToken}`);
  if (!res.ok) {
    throw new Error(`Không thể tải menu (${res.status})`);
  }
  return res.json() as Promise<QRResolveResponse>;
}

/**
 * Submit an order for the current table session.
 */
export async function createOrder(
  qrToken: string,
  body: CreateOrderRequest
): Promise<CreateOrderResponse> {
  const res = await fetch(`${BASE_URL}/t/${qrToken}/orders`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Lỗi gửi order (${res.status})`);
  }
  return res.json() as Promise<CreateOrderResponse>;
}


/**
 * Get session snapshot for resync (R4.8).
 */
export async function getSession(qrToken: string): Promise<SessionSnapshot> {
  const res = await fetch(`${BASE_URL}/t/${qrToken}/session`);
  if (!res.ok) {
    throw new Error(`Không thể tải phiên (${res.status})`);
  }
  return res.json() as Promise<SessionSnapshot>;
}

/**
 * Call staff to the table (R7.1).
 * Returns { created: true, data } for 201, { created: false, data } for 200 (cooldown).
 */
export async function callStaff(
  qrToken: string
): Promise<
  | { created: true; data: StaffCallResponse }
  | { created: false; data: StaffCallCooldownResponse }
> {
  const res = await fetch(`${BASE_URL}/t/${qrToken}/call`, {
    method: "POST",
  });

  if (res.status === 201) {
    const data = (await res.json()) as StaffCallResponse;
    return { created: true, data };
  }
  if (res.status === 200) {
    const data = (await res.json()) as StaffCallCooldownResponse;
    return { created: false, data };
  }

  throw new Error(`Gọi nhân viên thất bại (${res.status})`);
}

/**
 * Cancel a pending item (R11.2).
 * Returns the updated item on success, throws on 409 (conflict) or other errors.
 */
export async function cancelItem(
  qrToken: string,
  itemId: string,
  reason?: string
): Promise<SessionItem> {
  const body = reason ? JSON.stringify({ reason }) : undefined;
  const headers: HeadersInit = body
    ? { "Content-Type": "application/json" }
    : {};

  const res = await fetch(`${BASE_URL}/t/${qrToken}/items/${itemId}/cancel`, {
    method: "POST",
    headers,
    body,
  });

  if (res.status === 409) {
    throw new Error("Món đã thay đổi trạng thái, không thể huỷ.");
  }
  if (!res.ok) {
    throw new Error(`Huỷ món thất bại (${res.status})`);
  }
  return res.json() as Promise<SessionItem>;
}
