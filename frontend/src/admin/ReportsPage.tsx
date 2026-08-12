/**
 * Reports Page — show report sync info / trigger sync.
 */

import { useState } from "react";
import { useAdminAuth } from "./AdminAuthContext";

export default function ReportsPage() {
  const { token } = useAdminAuth();
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState("");

  const handleTriggerSync = async () => {
    if (!token) return;
    setSyncing(true);
    setMessage("");
    try {
      const res = await fetch(
        `${import.meta.env.VITE_API_BASE_URL || ""}/admin/reports/sync`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
        }
      );
      if (res.ok) {
        setMessage("✅ Đã trigger đồng bộ báo cáo thành công!");
      } else if (res.status === 404) {
        setMessage(
          "ℹ️ Tính năng đồng bộ sẽ chạy tự động theo lịch (cron). Endpoint chưa được cài đặt."
        );
      } else {
        setMessage(`⚠️ Lỗi: ${res.status}`);
      }
    } catch {
      setMessage(
        "ℹ️ Tính năng đồng bộ sẽ chạy tự động theo lịch (cron)."
      );
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="space-y-6 max-w-2xl">
      <h1 className="text-2xl font-bold text-gray-800">Báo cáo & Đồng bộ</h1>

      <div className="bg-white rounded-lg shadow p-6 space-y-4">
        <h2 className="text-lg font-semibold text-gray-700">
          Đồng bộ báo cáo lên Google Sheets
        </h2>

        <p className="text-gray-600 text-sm">
          Hệ thống tự động đồng bộ dữ liệu báo cáo lên Google Sheets theo lịch
          cron đã cấu hình trong Cài đặt. Bạn cũng có thể trigger thủ công bằng
          nút bên dưới.
        </p>

        <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-600 space-y-2">
          <p>
            <strong>Lịch chạy:</strong> Theo cấu hình{" "}
            <code className="bg-gray-200 px-1 rounded">report_sync_cron</code> trong
            Cài đặt
          </p>
          <p>
            <strong>Đích:</strong> Google Sheet ID được cấu hình trong{" "}
            <code className="bg-gray-200 px-1 rounded">report_sheet_id</code>
          </p>
        </div>

        <button
          onClick={handleTriggerSync}
          disabled={syncing}
          className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          {syncing ? "Đang đồng bộ..." : "🔄 Trigger đồng bộ ngay"}
        </button>

        {message && (
          <p className="text-sm text-gray-700 bg-blue-50 px-4 py-2 rounded-lg">
            {message}
          </p>
        )}
      </div>
    </div>
  );
}
