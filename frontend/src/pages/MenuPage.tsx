import { useEffect, useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import { resolveQR, createOrder, getSession, callStaff, cancelItem } from "../api";
import { useCart } from "../hooks/useCart";
import { useWebSocket } from "../hooks/useWebSocket";
import type {
  QRResolveResponse,
  MenuItem,
  CreateOrderRequest,
  SessionItem,
  WsEvent,
} from "../types";
import MenuCategorySection from "../components/MenuCategorySection";
import Cart from "../components/Cart";
import OrderStatusPanel from "../components/OrderStatusPanel";
import CallStaffButton from "../components/CallStaffButton";

export default function MenuPage() {
  const { qrToken } = useParams<{ slug: string; qrToken: string }>();
  const [data, setData] = useState<QRResolveResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [cartOpen, setCartOpen] = useState(false);

  // Session & realtime state
  const [sessionItems, setSessionItems] = useState<SessionItem[]>([]);
  const [sessionLoaded, setSessionLoaded] = useState(false);
  const [minSeq, setMinSeq] = useState(0);
  const [sessionStatus, setSessionStatus] = useState<string>("open");
  const [cancellingId, setCancellingId] = useState<string | null>(null);

  const cart = useCart();

  // Load menu data
  useEffect(() => {
    if (!qrToken) return;
    setLoading(true);
    resolveQR(qrToken)
      .then((res) => {
        setData(res);
        setError(null);
      })
      .catch((err: Error) => {
        setError(err.message);
      })
      .finally(() => setLoading(false));
  }, [qrToken]);

  // Load session snapshot after menu loaded
  useEffect(() => {
    if (!qrToken || !data) return;
    getSession(qrToken)
      .then((snapshot) => {
        setSessionItems(snapshot.items);
        setSessionStatus(snapshot.status);
        // Use last_activity_at as baseline seq for anti-stale filtering
        const baseSeq = new Date(snapshot.last_activity_at).getTime() * 1_000_000;
        setMinSeq(baseSeq);
        setSessionLoaded(true);
      })
      .catch(() => {
        // Session might not exist yet — that's fine
        setSessionLoaded(true);
      });
  }, [qrToken, data]);

  // Handle WS events
  const handleWsEvent = useCallback((event: WsEvent) => {
    switch (event.type) {
      case "item.updated": {
        const item = (event as Record<string, unknown>).item as
          | Partial<SessionItem>
          | undefined;
        if (item?.id) {
          setSessionItems((prev) =>
            prev.map((i) =>
              i.id === item.id
                ? { ...i, status: item.status ?? i.status, served_at: item.served_at ?? i.served_at }
                : i
            )
          );
        }
        break;
      }
      case "item.cancelled": {
        const item = (event as Record<string, unknown>).item as
          | Partial<SessionItem>
          | undefined;
        if (item?.id) {
          setSessionItems((prev) =>
            prev.map((i) =>
              i.id === item.id
                ? { ...i, status: "cancelled", cancelled_at: new Date().toISOString() }
                : i
            )
          );
        }
        break;
      }
      case "order.created": {
        const order = (event as Record<string, unknown>).order as
          | { items?: SessionItem[] }
          | undefined;
        if (order?.items) {
          // Merge new items (may come from another device on same table)
          setSessionItems((prev) => {
            const existingIds = new Set(prev.map((i) => i.id));
            const newItems = order.items!.filter((i) => !existingIds.has(i.id));
            return [...prev, ...newItems];
          });
        }
        break;
      }
      case "session.closed": {
        setSessionStatus("closed");
        break;
      }
      case "session.abandoned": {
        setSessionStatus("abandoned");
        break;
      }
    }
  }, []);

  // Connect WebSocket after session snapshot is loaded
  useWebSocket({
    qrToken,
    enabled: sessionLoaded,
    minSeq,
    onEvent: handleWsEvent,
  });

  const handleAddItem = (item: MenuItem) => {
    if (!item.is_available) return;
    cart.addItem(item);
  };

  const handleSubmitOrder = async () => {
    if (!qrToken || cart.items.length === 0) return;

    const body: CreateOrderRequest = {
      items: cart.items.map((ci) => ({
        menu_item_id: ci.menu_item_id,
        quantity: ci.quantity,
        note: ci.note.trim() || null,
      })),
    };

    setSubmitting(true);
    try {
      const response = await createOrder(qrToken, body);
      cart.clearCart();
      setCartOpen(false);
      setSuccessMsg("Đã gửi order thành công! Món đang được chuẩn bị.");
      setTimeout(() => setSuccessMsg(null), 4000);

      // Add new items to session state immediately
      const newItems: SessionItem[] = response.items.map((oi) => ({
        id: oi.id,
        order_id: response.id,
        menu_item_id: oi.menu_item_id,
        name_snapshot: oi.name_snapshot,
        price_snapshot: oi.price_snapshot,
        prep_time_snapshot: oi.prep_time_snapshot,
        quantity: oi.quantity,
        note: oi.note,
        status: oi.status as SessionItem["status"],
        requested_at: oi.requested_at,
        served_at: null,
        cancelled_at: null,
        cancelled_by: null,
        cancel_reason: null,
      }));
      setSessionItems((prev) => [...prev, ...newItems]);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Lỗi không xác định";
      alert(`Gửi order thất bại: ${message}`);
    } finally {
      setSubmitting(false);
    }
  };

  // Cancel pending item (R11.2)
  const handleCancelItem = async (itemId: string) => {
    if (!qrToken || cancellingId) return;
    setCancellingId(itemId);
    try {
      await cancelItem(qrToken, itemId);
      // Optimistic update
      setSessionItems((prev) =>
        prev.map((i) =>
          i.id === itemId
            ? { ...i, status: "cancelled" as const, cancelled_at: new Date().toISOString() }
            : i
        )
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Lỗi không xác định";
      alert(msg);
    } finally {
      setCancellingId(null);
    }
  };

  // Call staff (R7.1)
  const handleCallStaff = async () => {
    if (!qrToken) throw new Error("No token");
    const result = await callStaff(qrToken);
    if (result.created) {
      return { created: true };
    }
    return { created: false, message: result.data.message };
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-orange-500 mx-auto"></div>
          <p className="mt-3 text-gray-500">Đang tải menu...</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex items-center justify-center min-h-screen p-4">
        <div className="text-center">
          <p className="text-red-500 text-lg font-medium">
            {error || "Không tìm thấy dữ liệu"}
          </p>
          <p className="text-gray-500 mt-2">
            Vui lòng quét lại mã QR hoặc liên hệ nhân viên.
          </p>
        </div>
      </div>
    );
  }

  const isSessionEnded = sessionStatus === "closed" || sessionStatus === "abandoned";

  return (
    <div className="min-h-screen pb-24">
      {/* Header */}
      <header className="sticky top-0 z-30 bg-white shadow-sm border-b">
        <div className="max-w-lg mx-auto px-4 py-3 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-gray-900">
              {data.restaurant.name}
            </h1>
            <p className="text-sm text-gray-500">{data.table.table_number}</p>
          </div>
          {data.restaurant.logo_url && (
            <img
              src={data.restaurant.logo_url}
              alt={data.restaurant.name}
              className="h-10 w-10 rounded-full object-cover"
            />
          )}
        </div>
      </header>

      {/* Session ended notice */}
      {isSessionEnded && (
        <div className="max-w-lg mx-auto px-4 mt-4">
          <div className="bg-yellow-50 border border-yellow-200 text-yellow-800 text-sm rounded-lg p-3 text-center">
            {sessionStatus === "closed"
              ? "Phiên đã kết thúc. Cảm ơn quý khách!"
              : "Phiên đã hết hạn. Vui lòng liên hệ nhân viên."}
          </div>
        </div>
      )}

      {/* Success toast */}
      {successMsg && (
        <div className="fixed top-16 left-1/2 -translate-x-1/2 z-50 bg-green-500 text-white px-4 py-2 rounded-lg shadow-lg text-sm animate-pulse">
          {successMsg}
        </div>
      )}

      {/* Main content */}
      <main className="max-w-lg mx-auto px-4 py-4 space-y-6">
        {/* Order status panel (R4.2) */}
        <OrderStatusPanel
          items={sessionItems}
          onCancelItem={handleCancelItem}
          cancellingId={cancellingId}
        />

        {/* Menu content */}
        {data.menu.map((category) => (
          <MenuCategorySection
            key={category.id}
            category={category}
            onAddItem={handleAddItem}
            cartItems={cart.items}
          />
        ))}
      </main>

      {/* Call staff FAB (R7.1) — visible when session is open */}
      {!isSessionEnded && <CallStaffButton onCall={handleCallStaff} />}

      {/* Floating cart button */}
      {cart.totalItems > 0 && !isSessionEnded && (
        <div className="fixed bottom-0 left-0 right-0 z-40 p-4 bg-white border-t shadow-lg">
          <button
            onClick={() => setCartOpen(true)}
            className="w-full max-w-lg mx-auto flex items-center justify-between bg-orange-500 hover:bg-orange-600 text-white font-semibold py-3 px-5 rounded-xl transition-colors"
          >
            <span className="flex items-center gap-2">
              <svg
                xmlns="http://www.w3.org/2000/svg"
                className="h-5 w-5"
                viewBox="0 0 20 20"
                fill="currentColor"
              >
                <path d="M3 1a1 1 0 000 2h1.22l.305 1.222a.997.997 0 00.01.042l1.358 5.43-.893.892C3.74 11.846 4.632 14 6.414 14H15a1 1 0 000-2H6.414l1-1H14a1 1 0 00.894-.553l3-6A1 1 0 0017 3H6.28l-.31-1.243A1 1 0 005 1H3zM16 16.5a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0zM6.5 18a1.5 1.5 0 100-3 1.5 1.5 0 000 3z" />
              </svg>
              <span>Giỏ hàng ({cart.totalItems})</span>
            </span>
            <span>{formatPrice(cart.totalAmount, data.restaurant.currency)}</span>
          </button>
        </div>
      )}

      {/* Cart modal */}
      {cartOpen && (
        <Cart
          items={cart.items}
          currency={data.restaurant.currency}
          onClose={() => setCartOpen(false)}
          onUpdateQuantity={cart.updateQuantity}
          onUpdateNote={cart.updateNote}
          onRemoveItem={cart.removeItem}
          onSubmit={handleSubmitOrder}
          submitting={submitting}
          totalAmount={cart.totalAmount}
        />
      )}
    </div>
  );
}

function formatPrice(amount: number, currency: string): string {
  if (currency === "VND") {
    return amount.toLocaleString("vi-VN") + "đ";
  }
  return amount.toLocaleString() + " " + currency;
}
