/** Kitchen-specific types */

export interface KitchenBoardItem {
  id: string;
  order_id: string;
  menu_item_id: string;
  name_snapshot: string;
  price_snapshot: string;
  prep_time_snapshot: number;
  quantity: number;
  note: string | null;
  status: "pending" | "cooking" | "ready";
  requested_at: string;
  overdue_level: number | null;
}

export interface KitchenBoardResponse {
  items: KitchenBoardItem[];
}

export interface StaffCall {
  id: string;
  table_id: string;
  table_label?: string;
  table_session_id: string;
  status: string;
  created_at: string;
  acknowledged_at: string | null;
}

export interface CheckoutResult {
  session: {
    id: string;
    table_id: string;
    status: string;
    total_amount: string | null;
    closed_at: string | null;
  };
  total_amount: string;
  auto_cancelled_items: {
    id: string;
    name_snapshot: string;
    quantity: number;
    status_before: string;
  }[];
  dismissed_calls_count: number;
}

export interface KitchenWsEvent {
  type: string;
  seq?: number;
  item?: Partial<KitchenBoardItem> & { id: string };
  order?: { id: string; items: KitchenBoardItem[] };
  call?: StaffCall;
  session?: { id: string; table_id: string; status: string };
  [key: string]: unknown;
}
