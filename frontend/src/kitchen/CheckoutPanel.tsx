/**
 * CheckoutPanel — shows sessions with items, allows checkout.
 * Warns if session has non-served items (R6.7).
 */

import { useState } from "react";
import type { KitchenBoardItem, CheckoutResult } from "./types";

interface SessionGroup {
  sessionId: string;
  items: KitchenBoardItem[];
}

interface CheckoutPanelProps {
  /** Board items grouped by order → session */
  items: KitchenBoardItem[];
  /** Map of order_id → session_id (populated from context) */
  orderSessionMap: Map<string, string>;
  onCheckout: (sessionId: string) => Promise<CheckoutResult>;
}

export default function CheckoutPanel({
  items,
  orderSessionMap,
  onCheckout,
}: CheckoutPanelProps) {
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CheckoutResult | null>(null);
  const [error, setError] = useState("");

  // Group items by session
  const sessionGroups: SessionGroup[] = [];
  const sessionMap = new Map<string, KitchenBoardItem[]>();

  for (const item of items) {
    const sessionId = orderSessionMap.get(item.order_id);
    if (!sessionId) continue;
    if (!sessionMap.has(sessionId)) {
      sessionMap.set(sessionId, []);
    }
    sessionMap.get(sessionId)!.push(item);
  }

  for (const [sessionId, sessionItems] of sessionMap) {
    sessionGroups.push({ sessionId, items: sessionItems });
  }

  const handleCheckout = async (sessionId: string) => {
    setLoading(true);
    setError("");
    try {
      const res = await onCheckout(sessionId);
      setResult(res);
      setConfirming(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Checkout thất bại");
    } finally {
      setLoading(false);
    }
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-4 right-4 z-40 py-3 px-5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white font-bold shadow-lg transition-colors"
      >
        💰 Checkout
      </button>
    );
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
      <div className="bg-gray-800 rounded-2xl w-full max-w-md max-h-[80vh] overflow-y-auto p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-white text-xl font-bold">Checkout bàn</h2>
          <button
            onClick={() => { setOpen(false); setResult(null); setConfirming(null); }}
            className="text-gray-400 hover:text-white text-2xl"
          >
            ×
          </button>
        </div>

        {result && (
          <div className="bg-green-900/50 border border-green-700 rounded-lg p-4 mb-4">
            <p className="text-green-300 font-bold">✅ Đã checkout</p>
            <p className="text-green-200 text-sm mt-1">
              Tổng: {Number(result.total_amount).toLocaleString()}đ
            </p>
            {result.auto_cancelled_items.length > 0 && (
              <p className="text-yellow-300 text-xs mt-1">
                Đã tự huỷ {result.auto_cancelled_items.length} món chưa phục vụ
              </p>
            )}
            <button
              onClick={() => setResult(null)}
              className="mt-2 text-sm text-green-300 underline"
            >
              Đóng
            </button>
          </div>
        )}

        {error && (
          <p className="text-red-400 text-sm mb-3">{error}</p>
        )}

        {sessionGroups.length === 0 && !result && (
          <p className="text-gray-400 text-sm">Không có bàn nào có món đang chờ.</p>
        )}

        {sessionGroups.map(({ sessionId, items: sessionItems }) => (
          <div
            key={sessionId}
            className="border border-gray-700 rounded-lg p-3 mb-3"
          >
            <p className="text-gray-300 text-sm font-medium mb-2">
              Phiên: {sessionId.slice(0, 8)}...
            </p>
            <ul className="text-gray-400 text-xs space-y-0.5 mb-3">
              {sessionItems.map((item) => (
                <li key={item.id}>
                  • {item.name_snapshot} x{item.quantity}{" "}
                  <span className="text-yellow-400">({item.status})</span>
                </li>
              ))}
            </ul>

            {confirming === sessionId ? (
              <div className="space-y-2">
                <p className="text-yellow-300 text-xs font-semibold">
                  ⚠️ Bàn này còn {sessionItems.length} món chưa phục vụ. Xác nhận checkout?
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleCheckout(sessionId)}
                    disabled={loading}
                    className="flex-1 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white text-sm font-semibold disabled:opacity-50"
                  >
                    {loading ? "..." : "Xác nhận"}
                  </button>
                  <button
                    onClick={() => setConfirming(null)}
                    className="flex-1 py-2 rounded-lg bg-gray-600 hover:bg-gray-700 text-white text-sm"
                  >
                    Huỷ
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setConfirming(sessionId)}
                className="w-full py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold transition-colors"
              >
                Checkout
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
