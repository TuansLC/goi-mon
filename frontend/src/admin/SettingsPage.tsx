/**
 * Settings Page — edit restaurant settings + reset staff PIN.
 */

import { useState, useEffect, useCallback } from "react";
import { useAdminAuth } from "./AdminAuthContext";
import { getSettings, updateSettings, resetStaffPin } from "./api";
import type { RestaurantSettings } from "./types";

export default function SettingsPage() {
  const { token } = useAdminAuth();
  const [settings, setSettings] = useState<RestaurantSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  // PIN reset
  const [newPin, setNewPin] = useState("");
  const [pinMsg, setPinMsg] = useState("");

  const loadSettings = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const data = await getSettings(token);
      setSettings(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi tải cài đặt");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !settings) return;
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const updated = await updateSettings(token, settings);
      setSettings(updated);
      setSuccess("Đã lưu cài đặt thành công!");
      setTimeout(() => setSuccess(""), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi lưu cài đặt");
    } finally {
      setSaving(false);
    }
  };

  const handleResetPin = async () => {
    if (!token || !newPin.trim()) {
      setPinMsg("Vui lòng nhập PIN mới");
      return;
    }
    try {
      await resetStaffPin(token, newPin.trim());
      setPinMsg("✅ Đã đổi PIN thành công!");
      setNewPin("");
    } catch (err) {
      setPinMsg(err instanceof Error ? err.message : "Lỗi đổi PIN");
    }
  };

  if (loading) {
    return <div className="text-gray-500">Đang tải...</div>;
  }

  if (!settings) {
    return <div className="text-red-500">{error || "Không tải được cài đặt"}</div>;
  }

  return (
    <div className="space-y-8 max-w-2xl">
      <h1 className="text-2xl font-bold text-gray-800">Cài đặt nhà hàng</h1>

      {error && (
        <div className="bg-red-50 text-red-600 px-4 py-2 rounded-lg">{error}</div>
      )}
      {success && (
        <div className="bg-green-50 text-green-600 px-4 py-2 rounded-lg">{success}</div>
      )}

      <form onSubmit={handleSave} className="bg-white rounded-lg shadow p-6 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm text-gray-600 mb-1">Đơn vị tiền tệ</label>
            <input
              type="text"
              value={settings.currency}
              onChange={(e) =>
                setSettings({ ...settings, currency: e.target.value })
              }
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm text-gray-600 mb-1">Múi giờ</label>
            <input
              type="text"
              value={settings.timezone}
              onChange={(e) =>
                setSettings({ ...settings, timezone: e.target.value })
              }
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Asia/Ho_Chi_Minh"
            />
          </div>

          <div>
            <label className="block text-sm text-gray-600 mb-1">
              Thời gian mặc định món mặn (phút)
            </label>
            <input
              type="number"
              value={settings.default_savory_minutes}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  default_savory_minutes: parseInt(e.target.value) || 0,
                })
              }
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm text-gray-600 mb-1">
              Thời gian mặc định món nhẹ (phút)
            </label>
            <input
              type="number"
              value={settings.default_light_minutes}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  default_light_minutes: parseInt(e.target.value) || 0,
                })
              }
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm text-gray-600 mb-1">
              Session timeout (giờ)
            </label>
            <input
              type="number"
              value={settings.session_timeout_hours}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  session_timeout_hours: parseInt(e.target.value) || 1,
                })
              }
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm text-gray-600 mb-1">
              Staff call cooldown (giây)
            </label>
            <input
              type="number"
              value={settings.staff_call_cooldown_seconds}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  staff_call_cooldown_seconds: parseInt(e.target.value) || 30,
                })
              }
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm text-gray-600 mb-1">Logo URL</label>
          <input
            type="text"
            value={settings.logo_url || ""}
            onChange={(e) =>
              setSettings({ ...settings, logo_url: e.target.value || null })
            }
            className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="https://..."
          />
        </div>

        <div>
          <label className="block text-sm text-gray-600 mb-1">
            Ghi chú cuối hóa đơn
          </label>
          <textarea
            value={settings.bill_footer_note || ""}
            onChange={(e) =>
              setSettings({
                ...settings,
                bill_footer_note: e.target.value || null,
              })
            }
            className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            rows={2}
          />
        </div>

        <div>
          <label className="block text-sm text-gray-600 mb-1">
            Report Sheet ID (Google Sheets)
          </label>
          <input
            type="text"
            value={settings.report_sheet_id || ""}
            onChange={(e) =>
              setSettings({
                ...settings,
                report_sheet_id: e.target.value || null,
              })
            }
            className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-sm text-gray-600 mb-1">
            Report sync cron
          </label>
          <input
            type="text"
            value={settings.report_sync_cron || ""}
            onChange={(e) =>
              setSettings({
                ...settings,
                report_sync_cron: e.target.value || null,
              })
            }
            className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="0 2 * * *"
          />
        </div>

        <div className="flex items-center gap-3">
          <input
            type="checkbox"
            id="pin-required"
            checked={settings.kitchen_screen_requires_pin}
            onChange={(e) =>
              setSettings({
                ...settings,
                kitchen_screen_requires_pin: e.target.checked,
              })
            }
            className="w-4 h-4 rounded border-gray-300"
          />
          <label htmlFor="pin-required" className="text-sm text-gray-700">
            Yêu cầu PIN khi vào màn hình bếp
          </label>
        </div>

        <button
          type="submit"
          disabled={saving}
          className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          {saving ? "Đang lưu..." : "Lưu cài đặt"}
        </button>
      </form>

      {/* Staff PIN Reset */}
      <div className="bg-white rounded-lg shadow p-6">
        <h2 className="text-lg font-semibold text-gray-700 mb-4">
          Đổi PIN nhân viên
        </h2>
        <div className="flex gap-3 items-end">
          <div className="flex-1">
            <label className="block text-sm text-gray-600 mb-1">PIN mới</label>
            <input
              type="text"
              value={newPin}
              onChange={(e) => setNewPin(e.target.value)}
              placeholder="VD: 1234"
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <button
            onClick={handleResetPin}
            className="px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700"
          >
            Đổi PIN
          </button>
        </div>
        {pinMsg && (
          <p className="mt-2 text-sm text-gray-600">{pinMsg}</p>
        )}
      </div>
    </div>
  );
}
