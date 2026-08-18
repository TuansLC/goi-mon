/** Types matching the backend API response schemas */

export interface Restaurant {
  name: string;
  slug: string;
  currency: string;
  logo_url: string | null;
}

export interface TableInfo {
  id: string;
  table_number: string;
}

export interface MenuItem {
  id: string;
  name: string;
  description: string | null;
  price: string; // Decimal as string from backend
  prep_time_minutes: number;
  is_available: boolean;
  /** 400x400 WebP thumbnail, null when the owner hasn't uploaded a photo. */
  image_url: string | null;
  /** Max-1000px WebP variant used by the lightbox. */
  image_large_url: string | null;
  is_featured: boolean;
  category_id: string;
}

export interface MenuCategory {
  id: string;
  name: string;
  sort_order: number;
  items: MenuItem[];
}

export interface QRResolveResponse {
  restaurant: Restaurant;
  table: TableInfo;
  menu: MenuCategory[];
}

/** Session snapshot types (R4.2, R4.8) */

export type OrderItemStatusType =
  | "pending"
  | "cooking"
  | "ready"
  | "served"
  | "cancelled";

export interface SessionItem {
  id: string;
  order_id: string;
  menu_item_id: string;
  name_snapshot: string;
  price_snapshot: string;
  prep_time_snapshot: number;
  quantity: number;
  note: string | null;
  status: OrderItemStatusType;
  requested_at: string;
  served_at: string | null;
  cancelled_at: string | null;
  cancelled_by: string | null;
  cancel_reason: string | null;
}

export interface SessionSnapshot {
  id: string;
  restaurant_id: string;
  table_id: string;
  status: "open" | "closed" | "abandoned";
  opened_by: string | null;
  opened_at: string;
  last_activity_at: string;
  closed_at: string | null;
  abandoned_at: string | null;
  total_amount: string | null;
  items: SessionItem[];
}

/** Staff call response types (R7.1) */

export interface StaffCallResponse {
  id: string;
  table_id: string;
  table_session_id: string;
  status: string;
  created_at: string;
}

export interface StaffCallCooldownResponse {
  message: string;
}

/** WebSocket event types */

export interface WsEvent {
  type: string;
  seq: number;
  [key: string]: unknown;
}

/** Cart types */

export interface CartItem {
  menu_item_id: string;
  name: string;
  price: number;
  quantity: number;
  note: string;
}

/** Order request/response */

export interface CreateOrderItemRequest {
  menu_item_id: string;
  quantity: number;
  note?: string | null;
}

export interface CreateOrderRequest {
  items: CreateOrderItemRequest[];
}

export interface OrderItemResponse {
  id: string;
  menu_item_id: string;
  name_snapshot: string;
  price_snapshot: string;
  prep_time_snapshot: number;
  quantity: number;
  note: string | null;
  status: string;
  requested_at: string;
}

export interface CreateOrderResponse {
  id: string;
  table_session_id: string;
  created_at: string;
  items: OrderItemResponse[];
}
