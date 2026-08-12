/**
 * Sessions Page — view/restore abandoned sessions.
 */

import { useState, useEffect, useCallback } from "react";
import { useAdminAuth } from "./AdminAuthContext";
import {
  listAbandonedSessions,
  restoreSession,
  checkoutSession,
} from "./api";
import type { AbandonedSession } from "./types";

export default function SessionsPage() {
  const { token } = useAdminAuth();
  const [sessions, setSessions] = useState<AbandonedSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionMsg, setActionMsg] = useState("");

  const loadData = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const data = await listAbandonedSessions(token);
      setSessions(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi tải phiên");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleRestore = async (session: AbandonedSession) => {
    if (!token) return;
    setActionMsg("");
    try {
      const result = await restoreSession(token, session.id);
      setActionMsg(
        `✅ Phiên bàn ${session.table_number || session.table_id} đã ${
          result.action === "restored" ? "khôi phục" : "checkout"
        }. Đã huỷ ${result.auto_cancelled_items.length} món, bỏ ${
          result.dismissed_calls_count
        } cuộc gọi.`
      );
      loadData();
    } catch (err) {
      setActionMsg(err instanceof Error ? err.message : "Lỗi khôi phục");
    }
  };

  const handleCheckout = async (session: AbandonedSession) => {
    if (!token) return;
    setActionMsg("");
    try {
      const result = await checkoutSession(token, session.id);
      setActionMsg(
        `✅ Đã checkout phiên bàn ${session.table_number || session.table_id}. Tổng: ${
          result.total_amount || "0"
        }`
      );
      loadData();
    } catch (err) {
      setActionMsg(err instanceof Error ? err.message : "Lỗi checkout");
    }
  };

  const formatDate = (iso: string) => {
    return new Date(iso).toLocaleString("vi-VN");
  };

  if (loading) {
    return <div className="text-gray-500">Đang tải...</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-800">Phiên Abandoned</h1>
        <button
          onClick={loadData}
          className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 text-sm"
        >
          🔄 Làm mới
        </button>
      </div>

      {error && (
        <div className="bg-red-50 text-red-600 px-4 py-2 rounded-lg">{error}</div>
      )}
      {actionMsg && (
        <div className="bg-blue-50 text-blue-700 px-4 py-2 rounded-lg">
          {actionMsg}
        </div>
      )}

      {sessions.length === 0 ? (
        <div className="text-center text-gray-400 py-12">
          Không có phiên abandoned nào
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-4 py-3 text-gray-600">Bàn</th>
                <th className="text-left px-4 py-3 text-gray-600">Bắt đầu</th>
                <th className="text-left px-4 py-3 text-gray-600">
                  Hoạt động cuối
                </th>
                <th className="text-left px-4 py-3 text-gray-600">Tổng tiền</th>
                <th className="text-right px-4 py-3 text-gray-600">Thao tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {sessions.map((s) => (
                <tr key={s.id}>
                  <td className="px-4 py-3 font-medium">
                    {s.table_number || s.table_id.slice(0, 8)}
                  </td>
                  <td className="px-4 py-3 text-gray-500">
                    {formatDate(s.started_at)}
                  </td>
                  <td className="px-4 py-3 text-gray-500">
                    {s.last_activity_at ? formatDate(s.last_activity_at) : "—"}
                  </td>
                  <td className="px-4 py-3">
                    {s.total_amount || "—"}
                  </td>
                  <td className="px-4 py-3 text-right space-x-2">
                    <button
                      onClick={() => handleRestore(s)}
                      className="px-3 py-1 bg-green-50 text-green-600 rounded hover:bg-green-100 text-sm"
                    >
                      Khôi phục
                    </button>
                    <button
                      onClick={() => handleCheckout(s)}
                      className="px-3 py-1 bg-blue-50 text-blue-600 rounded hover:bg-blue-100 text-sm"
                    >
                      Checkout
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
