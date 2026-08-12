/**
 * Table Management — CRUD tables, regenerate QR, download QR PNG.
 */

import { useState, useEffect, useCallback } from "react";
import { useAdminAuth } from "./AdminAuthContext";
import {
  listTables,
  createTable,
  updateTable,
  regenerateQr,
  getQrImageUrl,
} from "./api";
import type { Table } from "./types";

export default function TableManagementPage() {
  const { token } = useAdminAuth();
  const [tables, setTables] = useState<Table[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Form state
  const [showForm, setShowForm] = useState(false);
  const [editingTable, setEditingTable] = useState<Table | null>(null);
  const [tableNumber, setTableNumber] = useState("");

  // QR preview
  const [qrTableId, setQrTableId] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const data = await listTables(token);
      setTables(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi tải dữ liệu");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const openForm = (table?: Table) => {
    if (table) {
      setEditingTable(table);
      setTableNumber(table.table_number);
    } else {
      setEditingTable(null);
      setTableNumber("");
    }
    setShowForm(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !tableNumber.trim()) return;
    try {
      if (editingTable) {
        await updateTable(token, editingTable.id, {
          table_number: tableNumber.trim(),
        });
      } else {
        await createTable(token, { table_number: tableNumber.trim() });
      }
      setShowForm(false);
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi lưu bàn");
    }
  };

  const handleToggleActive = async (table: Table) => {
    if (!token) return;
    try {
      await updateTable(token, table.id, { is_active: !table.is_active });
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi cập nhật");
    }
  };

  const handleRegenerateQr = async (table: Table) => {
    if (!token) return;
    if (!confirm(`Tạo mã QR mới cho bàn ${table.table_number}? Mã cũ sẽ mất hiệu lực.`)) return;
    try {
      await regenerateQr(token, table.id);
      loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lỗi tạo QR mới");
    }
  };

  const handleDownloadQr = (table: Table) => {
    const url = getQrImageUrl(table.id);
    const link = document.createElement("a");
    link.href = url;
    link.download = `qr-ban-${table.table_number}.png`;
    link.click();
  };

  if (loading) {
    return <div className="text-gray-500">Đang tải...</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-800">Quản lý Bàn</h1>
        <button
          onClick={() => openForm()}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm"
        >
          + Thêm bàn
        </button>
      </div>

      {error && (
        <div className="bg-red-50 text-red-600 px-4 py-2 rounded-lg">
          {error}
        </div>
      )}

      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="bg-white p-4 rounded-lg shadow flex gap-3 items-end"
        >
          <div className="flex-1">
            <label className="block text-sm text-gray-600 mb-1">
              Số bàn / Tên bàn
            </label>
            <input
              type="text"
              value={tableNumber}
              onChange={(e) => setTableNumber(e.target.value)}
              placeholder="VD: 1, A1, VIP-01"
              className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              autoFocus
            />
          </div>
          <button
            type="submit"
            className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700"
          >
            {editingTable ? "Cập nhật" : "Tạo"}
          </button>
          <button
            type="button"
            onClick={() => setShowForm(false)}
            className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300"
          >
            Huỷ
          </button>
        </form>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {tables.map((table) => (
          <div
            key={table.id}
            className={`bg-white rounded-lg shadow p-4 border-l-4 ${
              table.is_active ? "border-green-500" : "border-gray-300"
            }`}
          >
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-lg font-semibold text-gray-800">
                Bàn {table.table_number}
              </h3>
              <span
                className={`px-2 py-1 rounded text-xs ${
                  table.is_active
                    ? "bg-green-100 text-green-700"
                    : "bg-red-100 text-red-700"
                }`}
              >
                {table.is_active ? "Hoạt động" : "Ẩn"}
              </span>
            </div>

            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => openForm(table)}
                className="px-3 py-1 text-sm bg-blue-50 text-blue-600 rounded hover:bg-blue-100"
              >
                Sửa
              </button>
              <button
                onClick={() => handleToggleActive(table)}
                className="px-3 py-1 text-sm bg-orange-50 text-orange-600 rounded hover:bg-orange-100"
              >
                {table.is_active ? "Ẩn" : "Hiện"}
              </button>
              <button
                onClick={() => handleRegenerateQr(table)}
                className="px-3 py-1 text-sm bg-purple-50 text-purple-600 rounded hover:bg-purple-100"
              >
                🔄 QR mới
              </button>
              <button
                onClick={() => setQrTableId(qrTableId === table.id ? null : table.id)}
                className="px-3 py-1 text-sm bg-gray-50 text-gray-600 rounded hover:bg-gray-100"
              >
                👁 Xem QR
              </button>
              <button
                onClick={() => handleDownloadQr(table)}
                className="px-3 py-1 text-sm bg-green-50 text-green-600 rounded hover:bg-green-100"
              >
                ⬇ Tải QR
              </button>
            </div>

            {qrTableId === table.id && (
              <div className="mt-3 flex justify-center">
                <img
                  src={getQrImageUrl(table.id)}
                  alt={`QR bàn ${table.table_number}`}
                  className="w-48 h-48 border rounded"
                />
              </div>
            )}
          </div>
        ))}
      </div>

      {tables.length === 0 && (
        <div className="text-center text-gray-400 py-8">Chưa có bàn nào</div>
      )}
    </div>
  );
}
