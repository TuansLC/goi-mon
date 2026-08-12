/**
 * KitchenBoard — Main kitchen display page.
 * - Fetches initial data from GET /kitchen/board
 * - Connects to WebSocket for real-time updates
 * - Displays items sorted by urgency (oldest first)
 * - Computes overdue_level client-side from requested_at + prep_time_snapshot
 * - Handles mark served, undo, cancel, staff calls, checkout
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useKitchenAuth } from "./AuthContext";
import { useKitchenWebSocket } from "./useKitchenWebSocket";
import {
  fetchKitchenBoard,
  getWsTicket,
  setItemStatus,
  cancelItemKitchen,
  ackStaffCall,
  checkoutSession,
} from "./api";
import type { KitchenBoardItem, StaffCall, KitchenWsEvent, CheckoutResult } from "./types";
import KitchenItemCard from "./KitchenItemCard";
import StaffCallNotification from "./StaffCallNotification";
import CheckoutPanel from "./CheckoutPanel";

/** Compute overdue_level client-side (R5.5, Property 6) */
function computeOverdueLevel(prepTime: number, requestedAt: string): number | null {
  if (prepTime === 0) return null; // R5.1
  const elapsed = (Date.now() - new Date(requestedAt).getTime()) / 60000; // minutes
  const ratio = elapsed / prepTime;
  if (ratio < 1.0) return 0;
  if (ratio < 1.5) return 1;
  if (ratio < 2.0) return 2;
  return 3;
}

export default function KitchenBoard() {
  const { token, slug, logout } = useKitchenAuth();
  const navigate = useNavigate();

  const [items, setItems] = useState<KitchenBoardItem[]>([]);
  const [staffCalls, setStaffCalls] = useState<StaffCall[]>([]);
  const [ticket, setTicket] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // Track recently-served items for undo (id → timestamp when served was clicked)
  const [servedMap, setServedMap] = useState<Map<string, number>>(new Map());
  // Map order_id → session_id (from WS events or initial data)
  const orderSessionMapRef = useRef<Map<string, string>>(new Map());
  // Periodic overdue level update
  const [, setTick] = useState(0);

  // Redirect to login if no slug
  useEffect(() => {
    if (!slug) {
      navigate("/kitchen", { replace: true });
    }
  }, [slug, navigate]);

  // Periodic tick to update overdue levels (every 10s)
  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 10000);
    return () => clearInterval(interval);
  }, []);

  // Load board data
  const loadBoard = useCallback(async () => {
    try {
      const data = await fetchKitchenBoard(token);
      setItems(data.items);
      setError("");
    } catch (err) {
      if (err instanceof Error && err.message === "UNAUTHORIZED") {
        logout();
        navigate("/kitchen", { replace: true });
        return;
      }
      setError(err instanceof Error ? err.message : "Lỗi tải dữ liệu");
    } finally {
      setLoading(false);
    }
  }, [token, logout, navigate]);

  // Initial load + get WS ticket
  useEffect(() => {
    if (!slug) return;

    const init = async () => {
      await loadBoard();
      try {
        const t = await getWsTicket(slug, token);
        setTicket(t);
      } catch (err) {
        console.error("Failed to get WS ticket:", err);
      }
    };
    init();
  }, [slug, token, loadBoard]);

  // Handle WS events
  const handleWsEvent = useCallback((event: KitchenWsEvent) => {
    switch (event.type) {
      case "item.updated": {
        if (!event.item) break;
        const updated = event.item;
        setItems((prev) => {
          // If status is served/cancelled, remove from board
          if (updated.status === "served" || updated.status === "cancelled") {
            return prev.filter((i) => i.id !== updated.id);
          }
          // Update existing item
          const idx = prev.findIndex((i) => i.id === updated.id);
          if (idx >= 0) {
            const newItems = [...prev];
            newItems[idx] = { ...newItems[idx], ...updated } as KitchenBoardItem;
            return newItems;
          }
          return prev;
        });
        break;
      }
      case "item.cancelled": {
        if (!event.item) break;
        setItems((prev) => prev.filter((i) => i.id !== event.item!.id));
        break;
      }
      case "order.created": {
        if (!event.order) break;
        const newItems = event.order.items || [];
        // Track order→session mapping
        if (event.order.id && (event as Record<string, unknown>).table_session_id) {
          orderSessionMapRef.current.set(
            event.order.id,
            (event as Record<string, unknown>).table_session_id as string
          );
        }
        setItems((prev) => [...prev, ...newItems]);
        break;
      }
      case "staff_call.new": {
        if (!event.call) break;
        setStaffCalls((prev) => [...prev, event.call!]);
        break;
      }
      case "staff_call.ack": {
        if (!event.call) break;
        setStaffCalls((prev) => prev.filter((c) => c.id !== event.call!.id));
        break;
      }
      case "session.closed":
      case "session.abandoned": {
        // Remove items belonging to this session's orders
        // We'll just resync from board to be safe
        loadBoard();
        break;
      }
      default:
        break;
    }
  }, [loadBoard]);

  // Connect WebSocket
  useKitchenWebSocket({
    ticket,
    enabled: !!ticket,
    onEvent: handleWsEvent,
    onReconnect: loadBoard,
  });

  // Actions
  const handleMarkServed = async (itemId: string) => {
    try {
      await setItemStatus(itemId, "served", token);
      // Track for undo
      setServedMap((prev) => {
        const m = new Map(prev);
        m.set(itemId, Date.now());
        return m;
      });
      // Remove from active list (WS will also notify)
      setItems((prev) => prev.filter((i) => i.id !== itemId));
    } catch (err) {
      if (err instanceof Error && err.message === "UNAUTHORIZED") {
        logout();
        navigate("/kitchen", { replace: true });
      }
    }
  };

  const handleUndo = async (itemId: string) => {
    try {
      await setItemStatus(itemId, "pending", token);
      setServedMap((prev) => {
        const m = new Map(prev);
        m.delete(itemId);
        return m;
      });
      // Item will reappear via WS or we re-fetch
      loadBoard();
    } catch (err) {
      if (err instanceof Error && err.message === "UNAUTHORIZED") {
        logout();
        navigate("/kitchen", { replace: true });
      }
    }
  };

  const handleCancel = async (itemId: string) => {
    try {
      await cancelItemKitchen(itemId, undefined, token);
      setItems((prev) => prev.filter((i) => i.id !== itemId));
    } catch (err) {
      if (err instanceof Error && err.message === "UNAUTHORIZED") {
        logout();
        navigate("/kitchen", { replace: true });
      }
    }
  };

  const handleAckCall = async (callId: string) => {
    try {
      await ackStaffCall(callId, token);
      setStaffCalls((prev) => prev.filter((c) => c.id !== callId));
    } catch (err) {
      if (err instanceof Error && err.message === "UNAUTHORIZED") {
        logout();
        navigate("/kitchen", { replace: true });
      }
    }
  };

  const handleCheckout = async (sessionId: string): Promise<CheckoutResult> => {
    const result = await checkoutSession(sessionId, token);
    // Remove items from board for this session
    loadBoard();
    return result;
  };

  // Sort items: oldest first (most urgent)
  const sortedItems = [...items].sort(
    (a, b) => new Date(a.requested_at).getTime() - new Date(b.requested_at).getTime()
  );

  // Compute client-side overdue levels
  const itemsWithLevel = sortedItems.map((item) => ({
    ...item,
    overdue_level: computeOverdueLevel(item.prep_time_snapshot, item.requested_at),
  }));

  // Recently served items for undo display
  const recentlyServed = Array.from(servedMap.entries())
    .filter(([, ts]) => Date.now() - ts < 2 * 60 * 1000)
    .map(([id, ts]) => ({ id, servedAt: ts }));

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-900 flex items-center justify-center">
        <p className="text-gray-400 text-lg">Đang tải bảng bếp...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-900 p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-white text-xl font-bold">🍳 Bếp — {slug}</h1>
        <div className="flex gap-2">
          <button
            onClick={loadBoard}
            className="py-2 px-3 rounded-lg bg-gray-700 hover:bg-gray-600 text-gray-200 text-sm transition-colors"
          >
            🔄
          </button>
          <button
            onClick={() => { logout(); navigate("/kitchen", { replace: true }); }}
            className="py-2 px-3 rounded-lg bg-gray-700 hover:bg-gray-600 text-gray-200 text-sm transition-colors"
          >
            Đăng xuất
          </button>
        </div>
      </div>

      {error && (
        <p className="text-red-400 text-sm mb-3 text-center">{error}</p>
      )}

      {/* Staff call notifications */}
      <StaffCallNotification calls={staffCalls} onAck={handleAckCall} />

      {/* Main board grid */}
      {itemsWithLevel.length === 0 && recentlyServed.length === 0 && (
        <div className="flex items-center justify-center h-[60vh]">
          <p className="text-gray-500 text-lg">Không có món nào đang chờ 🎉</p>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {itemsWithLevel.map((item) => (
          <KitchenItemCard
            key={item.id}
            id={item.id}
            name_snapshot={item.name_snapshot}
            quantity={item.quantity}
            note={item.note}
            status={item.status}
            requested_at={item.requested_at}
            prep_time_snapshot={item.prep_time_snapshot}
            overdue_level={item.overdue_level}
            onMarkServed={handleMarkServed}
            onUndo={handleUndo}
            onCancel={handleCancel}
          />
        ))}

        {/* Recently served items (undo) */}
        {recentlyServed.map(({ id, servedAt }) => (
          <div
            key={`undo-${id}`}
            className="bg-gray-800/50 border border-green-800 rounded-xl p-4"
          >
            <p className="text-green-400 text-sm font-medium mb-2">✅ Đã phục vụ</p>
            <p className="text-gray-400 text-xs mb-2">ID: {id.slice(0, 8)}...</p>
            <KitchenItemCard
              id={id}
              name_snapshot="(đã phục vụ)"
              quantity={0}
              note={null}
              status="pending"
              requested_at=""
              prep_time_snapshot={0}
              overdue_level={null}
              onMarkServed={() => {}}
              onUndo={handleUndo}
              onCancel={() => {}}
              servedAt={servedAt}
            />
          </div>
        ))}
      </div>

      {/* Checkout panel */}
      <CheckoutPanel
        items={items}
        orderSessionMap={orderSessionMapRef.current}
        onCheckout={handleCheckout}
      />
    </div>
  );
}
