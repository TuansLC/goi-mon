/** Kitchen API helpers */

import type { KitchenBoardResponse, CheckoutResult } from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

function authHeaders(token: string | null): HeadersInit {
  const headers: HeadersInit = { "Content-Type": "application/json" };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

/**
 * Staff login with PIN.
 */
export async function staffLogin(
  restaurantSlug: string,
  pin: string
): Promise<{ access_token: string; token_type: string }> {
  const res = await fetch(`${BASE_URL}/auth/staff/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ restaurant_slug: restaurantSlug, pin }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `Đăng nhập thất bại (${res.status})`);
  }
  return res.json();
}

/**
 * Get WS ticket. If PIN is not required, token can be null.
 */
export async function getWsTicket(
  restaurantSlug: string,
  token: string | null
): Promise<string> {
  const headers: HeadersInit = { "Content-Type": "application/json" };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${BASE_URL}/auth/ws-ticket`, {
    method: "POST",
    headers,
    body: JSON.stringify({ restaurant_slug: restaurantSlug }),
  });
  if (!res.ok) {
    throw new Error(`Không lấy được WS ticket (${res.status})`);
  }
  const data = await res.json();
  return data.ticket as string;
}

/**
 * Fetch kitchen board (requires Staff JWT).
 */
export async function fetchKitchenBoard(
  token: string | null
): Promise<KitchenBoardResponse> {
  const res = await fetch(`${BASE_URL}/kitchen/board`, {
    headers: authHeaders(token),
  });
  if (res.status === 401) {
    throw new Error("UNAUTHORIZED");
  }
  if (!res.ok) {
    throw new Error(`Lỗi tải bảng bếp (${res.status})`);
  }
  return res.json();
}

/**
 * Set item status (served, cooking, ready, pending for undo).
 */
export async function setItemStatus(
  itemId: string,
  to: string,
  token: string | null
): Promise<unknown> {
  const res = await fetch(`${BASE_URL}/kitchen/items/${itemId}/status`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ to }),
  });
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (res.status === 409) throw new Error("CONFLICT");
  if (!res.ok) throw new Error(`Lỗi đổi trạng thái (${res.status})`);
  return res.json();
}

/**
 * Cancel an item from the kitchen.
 */
export async function cancelItemKitchen(
  itemId: string,
  reason: string | undefined,
  token: string | null
): Promise<unknown> {
  const res = await fetch(`${BASE_URL}/kitchen/items/${itemId}/cancel`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ reason: reason || null }),
  });
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (res.status === 409) throw new Error("CONFLICT");
  if (!res.ok) throw new Error(`Lỗi huỷ món (${res.status})`);
  return res.json();
}

/**
 * Acknowledge a staff call.
 */
export async function ackStaffCall(
  callId: string,
  token: string | null
): Promise<unknown> {
  const res = await fetch(`${BASE_URL}/kitchen/calls/${callId}/ack`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (!res.ok) throw new Error(`Lỗi xác nhận gọi NV (${res.status})`);
  return res.json();
}

/**
 * Checkout a session.
 */
export async function checkoutSession(
  sessionId: string,
  token: string | null
): Promise<CheckoutResult> {
  const res = await fetch(
    `${BASE_URL}/tables/sessions/${sessionId}/checkout`,
    {
      method: "POST",
      headers: authHeaders(token),
    }
  );
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (res.status === 409) throw new Error("CONFLICT");
  if (!res.ok) throw new Error(`Lỗi checkout (${res.status})`);
  return res.json();
}
