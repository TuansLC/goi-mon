/** Admin-specific types */

export interface AdminLoginResponse {
  access_token: string;
  token_type: string;
}

export interface MenuCategory {
  id: string;
  name: string;
  sort_order: number;
  is_active: boolean;
  created_at: string;
}

export interface MenuItem {
  id: string;
  name: string;
  price: string;
  prep_time_minutes: number;
  category_id: string | null;
  description: string | null;
  image_url: string | null;
  image_large_url: string | null;
  is_featured: boolean;
  sort_order: number;
  is_available: boolean;
  is_active: boolean;
  created_at: string;
}

export interface PrepTimePresets {
  default_savory_minutes: number;
  default_light_minutes: number;
}

export interface Table {
  id: string;
  table_number: string;
  qr_token: string;
  qr_image_url: string | null;
  is_active: boolean;
  created_at: string;
}

export interface RestaurantSettings {
  kitchen_screen_requires_pin: boolean;
  currency: string;
  logo_url: string | null;
  timezone: string;
  default_savory_minutes: number;
  default_light_minutes: number;
  session_timeout_hours: number;
  staff_call_cooldown_seconds: number;
  report_sheet_id: string | null;
  report_sync_cron: string | null;
  bill_footer_note: string | null;
}

export interface AbandonedSession {
  id: string;
  table_id: string;
  table_number?: string;
  status: string;
  started_at: string;
  last_activity_at: string | null;
  total_amount: string | null;
}

export interface RestoreSessionResult {
  session: {
    id: string;
    table_id: string;
    status: string;
  };
  action: "restored" | "checked_out";
  total_amount?: string;
  auto_cancelled_items: {
    id: string;
    name_snapshot: string;
    quantity: number;
    status_before: string;
  }[];
  dismissed_calls_count: number;
}
