/** Admin API helpers */

import type {
  AdminLoginResponse,
  MenuCategory,
  MenuItem,
  PrepTimePresets,
  Table,
  RestaurantSettings,
  AbandonedSession,
  RestoreSessionResult,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

function authHeaders(token: string): HeadersInit {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (res.status === 401) throw new Error("UNAUTHORIZED");
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Lỗi (${res.status})`);
  }
  return res.json();
}

// --- Auth ---

export async function adminLogin(
  email: string,
  password: string
): Promise<AdminLoginResponse> {
  const res = await fetch(`${BASE_URL}/auth/admin/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || "Đăng nhập thất bại");
  }
  return res.json();
}

// --- Menu Categories ---

export async function listCategories(token: string): Promise<MenuCategory[]> {
  const res = await fetch(`${BASE_URL}/admin/menu-categories`, {
    headers: authHeaders(token),
  });
  return handleResponse<MenuCategory[]>(res);
}

export async function createCategory(
  token: string,
  data: { name: string; sort_order: number }
): Promise<MenuCategory> {
  const res = await fetch(`${BASE_URL}/admin/menu-categories`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(data),
  });
  return handleResponse<MenuCategory>(res);
}

export async function updateCategory(
  token: string,
  id: string,
  data: { name?: string; sort_order?: number; is_active?: boolean }
): Promise<MenuCategory> {
  const res = await fetch(`${BASE_URL}/admin/menu-categories/${id}`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(data),
  });
  return handleResponse<MenuCategory>(res);
}

// --- Menu Items ---

export async function listMenuItems(token: string): Promise<MenuItem[]> {
  const res = await fetch(`${BASE_URL}/admin/menu-items`, {
    headers: authHeaders(token),
  });
  return handleResponse<MenuItem[]>(res);
}

export async function createMenuItem(
  token: string,
  data: {
    name: string;
    price: number;
    prep_time_minutes: number;
    category_id?: string;
    description?: string;
    image_url?: string;
    sort_order?: number;
  }
): Promise<MenuItem> {
  const res = await fetch(`${BASE_URL}/admin/menu-items`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(data),
  });
  return handleResponse<MenuItem>(res);
}

export async function updateMenuItem(
  token: string,
  id: string,
  data: {
    name?: string;
    price?: number;
    prep_time_minutes?: number;
    category_id?: string;
    is_available?: boolean;
    is_active?: boolean;
    image_url?: string;
    is_featured?: boolean;
    sort_order?: number;
    description?: string;
  }
): Promise<MenuItem> {
  const res = await fetch(`${BASE_URL}/admin/menu-items/${id}`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(data),
  });
  return handleResponse<MenuItem>(res);
}

/**
 * Upload a photo for a menu item.
 *
 * Sent as multipart/form-data — no explicit Content-Type header, the browser has
 * to set it together with the multipart boundary.
 */
export async function uploadMenuItemImage(
  token: string,
  id: string,
  file: File
): Promise<MenuItem> {
  const form = new FormData();
  form.append("file", file);

  const res = await fetch(`${BASE_URL}/admin/menu-items/${id}/image`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  return handleResponse<MenuItem>(res);
}

export async function deleteMenuItemImage(
  token: string,
  id: string
): Promise<MenuItem> {
  const res = await fetch(`${BASE_URL}/admin/menu-items/${id}/image`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  return handleResponse<MenuItem>(res);
}

export async function getPrepTimePresets(
  token: string
): Promise<PrepTimePresets> {
  const res = await fetch(`${BASE_URL}/admin/settings/presets`, {
    headers: authHeaders(token),
  });
  return handleResponse<PrepTimePresets>(res);
}

// --- Tables ---

export async function listTables(token: string): Promise<Table[]> {
  const res = await fetch(`${BASE_URL}/admin/tables`, {
    headers: authHeaders(token),
  });
  return handleResponse<Table[]>(res);
}

export async function createTable(
  token: string,
  data: { table_number: string }
): Promise<Table> {
  const res = await fetch(`${BASE_URL}/admin/tables`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(data),
  });
  return handleResponse<Table>(res);
}

export async function updateTable(
  token: string,
  id: string,
  data: { table_number?: string; is_active?: boolean }
): Promise<Table> {
  const res = await fetch(`${BASE_URL}/admin/tables/${id}`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(data),
  });
  return handleResponse<Table>(res);
}

export async function regenerateQr(token: string, id: string): Promise<Table> {
  const res = await fetch(`${BASE_URL}/admin/tables/${id}/regenerate-qr`, {
    method: "POST",
    headers: authHeaders(token),
  });
  return handleResponse<Table>(res);
}

export function getQrImageUrl(id: string): string {
  return `${BASE_URL}/admin/tables/${id}/qr`;
}

// --- Settings ---

export async function getSettings(
  token: string
): Promise<RestaurantSettings> {
  const res = await fetch(`${BASE_URL}/admin/settings`, {
    headers: authHeaders(token),
  });
  return handleResponse<RestaurantSettings>(res);
}

export async function updateSettings(
  token: string,
  data: Partial<RestaurantSettings>
): Promise<RestaurantSettings> {
  const res = await fetch(`${BASE_URL}/admin/settings`, {
    method: "PATCH",
    headers: authHeaders(token),
    body: JSON.stringify(data),
  });
  return handleResponse<RestaurantSettings>(res);
}

// --- Staff PIN ---

export async function resetStaffPin(
  token: string,
  newPin: string
): Promise<void> {
  const res = await fetch(`${BASE_URL}/admin/staff/reset-pin`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ new_pin: newPin }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || "Lỗi đổi PIN");
  }
}

// --- Sessions ---

export async function listAbandonedSessions(
  token: string
): Promise<AbandonedSession[]> {
  const res = await fetch(`${BASE_URL}/admin/sessions?status=abandoned`, {
    headers: authHeaders(token),
  });
  return handleResponse<AbandonedSession[]>(res);
}

export async function restoreSession(
  token: string,
  sessionId: string
): Promise<RestoreSessionResult> {
  const res = await fetch(
    `${BASE_URL}/tables/sessions/${sessionId}/restore`,
    {
      method: "POST",
      headers: authHeaders(token),
    }
  );
  return handleResponse<RestoreSessionResult>(res);
}

export async function checkoutSession(
  token: string,
  sessionId: string
): Promise<RestoreSessionResult> {
  const res = await fetch(
    `${BASE_URL}/tables/sessions/${sessionId}/checkout`,
    {
      method: "POST",
      headers: authHeaders(token),
    }
  );
  return handleResponse<RestoreSessionResult>(res);
}
