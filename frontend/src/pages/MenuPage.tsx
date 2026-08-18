import { useEffect, useState, useCallback, useMemo } from "react";
import { useParams } from "react-router-dom";
import { resolveQR, createOrder, getSession, callStaff, cancelItem } from "../api";
import { useCart } from "../hooks/useCart";
import { useWebSocket } from "../hooks/useWebSocket";
import { formatPrice } from "../format";
import type {
  QRResolveResponse,
  MenuItem,
  CreateOrderRequest,
  SessionItem,
  WsEvent,
} from "../types";
import MenuCategorySection from "../components/MenuCategorySection";
import MyOrdersPanel from "../components/MyOrdersPanel";
import FeaturedCarousel from "../components/FeaturedCarousel";
import ImageLightbox from "../components/ImageLightbox";
import Cart from "../components/Cart";
import CallStaffButton from "../components/CallStaffButton";

type Tab = "menu" | "orders";

export default function MenuPage() {
  const { qrToken } = useParams<{ slug: string; qrToken: string }>();
  const [data, setData] = useState<QRResolveResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [cartOpen, setCartOpen] = useState(false);
  const [tab, setTab] = useState<Tab>("menu");
  const [zoomedItem, setZoomedItem] = useState<MenuItem | null>(null);

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
          | { id?: string; items?: SessionItem[] }
          | undefined;
        if (order?.items) {
          // Append only items we don't already know about. The WS payload is
          // partial (no price/prep_time), so never overwrite existing entries —
          // the REST response for our own order carries the full data.
          setSessionItems((prev) => {
            const existingIds = new Set(prev.map((i) => i.id));
            const newItems = order.items!.filter((i) => !existingIds.has(i.id));
            if (newItems.length === 0) return prev;
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

  /** Items still waiting to be served — drives the "Đơn của tôi" tab badge. */
  const waitingCount = useMemo(
    () =>
      sessionItems.filter(
        (i) => i.status !== "served" && i.status !== "cancelled"
      ).length,
    [sessionItems]
  );

  /**
   * Running subtotal of everything ordered so far, cancelled items excluded
   * (R11.5). This is an indication for the customer — the binding total is
   * computed by the server at checkout from served items only (R6.9).
   */
  const orderedSubtotal = useMemo(
    () =>
      sessionItems
        .filter((i) => i.status !== "cancelled")
        .reduce(
          (sum, i) => sum + (parseFloat(i.price_snapshot) || 0) * i.quantity,
          0
        ),
    [sessionItems]
  );

  /** Items the owner flagged as highlights, for the photo carousel. */
  const featuredItems = useMemo(
    () =>
      (data?.menu ?? [])
        .flatMap((category) => category.items)
        .filter((item) => item.is_featured),
    [data]
  );

  const handleAddItem = (item: MenuItem) => {
    if (!item.is_available) return;
    cart.addItem(item);
  };

  const handleSubmitOrder = async () => {
    if (!qrToken || cart.items.length === 0 || submitting) return;

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
      setTab("orders");
      setSuccessMsg("Đã gửi order thành công! Món đang được chuẩn bị.");
      setTimeout(() => setSuccessMsg(null), 4000);

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
      // Upsert by id: the WS `order.created` event usually arrives BEFORE this
      // HTTP response (Redis publishes before the response reaches the browser),
      // so these items may already be in state as partial WS entries. Merging by
      // id fills them in instead of appending duplicates.
      setSessionItems((prev) => {
        const byId = new Map(prev.map((i) => [i.id, i]));
        for (const item of newItems) {
          byId.set(item.id, { ...byId.get(item.id), ...item });
        }
        return Array.from(byId.values());
      });
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
      <div className="qo-page flex min-h-screen items-center justify-center">
        <div className="text-center">
          <div className="qo-spinner mx-auto h-10 w-10 animate-spin rounded-full" />
          <p className="qo-muted mt-3">Đang tải menu...</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="qo-page flex min-h-screen items-center justify-center p-4">
        <div className="text-center">
          <p className="text-lg font-semibold text-red-300">
            {error || "Không tìm thấy dữ liệu"}
          </p>
          <p className="qo-muted mt-2">
            Vui lòng quét lại mã QR hoặc liên hệ nhân viên.
          </p>
        </div>
      </div>
    );
  }

  const currency = data.restaurant.currency;
  const isSessionEnded =
    sessionStatus === "closed" || sessionStatus === "abandoned";

  return (
    <div className="qo-page min-h-screen pb-28">
      <div className="mx-auto max-w-lg">
        {/* Header */}
        <header className="qo-header rounded-b-3xl px-4 py-4">
          <div className="flex items-center gap-3">
            {data.restaurant.logo_url ? (
              <img
                src={data.restaurant.logo_url}
                alt={data.restaurant.name}
                className="h-10 w-10 rounded-xl object-cover"
              />
            ) : (
              <div
                className="qo-icon-badge flex h-10 w-10 items-center justify-center rounded-xl"
                aria-hidden="true"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  className="h-5 w-5"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                >
                  <path d="M3 5a1 1 0 011-1h9a1 1 0 011 1v1h1.5a2.5 2.5 0 010 5H14v1a3 3 0 01-3 3H6a3 3 0 01-3-3V5zm11 3v1h1.5a.5.5 0 000-1H14zM2 17a1 1 0 011-1h11a1 1 0 110 2H3a1 1 0 01-1-1z" />
                </svg>
              </div>
            )}
            <div className="min-w-0">
              <h1 className="truncate text-lg font-bold">
                {data.restaurant.name}
              </h1>
              <p className="qo-accent-soft text-sm">
                • Bàn {data.table.table_number}
              </p>
            </div>
          </div>
        </header>

        {/* Tabs */}
        <div className="qo-tabbar sticky top-0 z-30 px-4 py-3 backdrop-blur">
          <div role="tablist" aria-label="Chế độ xem" className="flex gap-2">
            <TabButton
              active={tab === "menu"}
              onClick={() => setTab("menu")}
              label="Gọi món"
            />
            <TabButton
              active={tab === "orders"}
              onClick={() => setTab("orders")}
              label="Đơn của tôi"
              badge={waitingCount}
            />
          </div>
        </div>

        {/* Session ended notice */}
        {isSessionEnded && (
          <div className="px-4 pb-1">
            <div className="qo-notice rounded-xl p-3 text-center text-sm">
              {sessionStatus === "closed"
                ? "Phiên đã kết thúc. Cảm ơn quý khách!"
                : "Phiên đã hết hạn. Vui lòng liên hệ nhân viên."}
            </div>
          </div>
        )}

        {/* Success toast */}
        {successMsg && (
          <div
            role="status"
            className="qo-toast-success fixed left-1/2 top-4 z-50 -translate-x-1/2 rounded-xl px-4 py-2 text-sm shadow-lg backdrop-blur"
          >
            {successMsg}
          </div>
        )}

        <main className="space-y-6 px-4 pb-4 pt-1">
          {tab === "menu" ? (
            <div role="tabpanel" aria-label="Gọi món" className="space-y-6">
              <FeaturedCarousel
                items={featuredItems}
                currency={currency}
                cartItems={cart.items}
                onAddItem={handleAddItem}
                onOpenImage={setZoomedItem}
              />

              {data.menu.map((category) => (
                <MenuCategorySection
                  key={category.id}
                  category={category}
                  currency={currency}
                  onAddItem={handleAddItem}
                  onOpenImage={setZoomedItem}
                  cartItems={cart.items}
                />
              ))}
            </div>
          ) : (
            <div role="tabpanel" aria-label="Đơn của tôi">
              <MyOrdersPanel
                items={sessionItems}
                currency={currency}
                onCancelItem={handleCancelItem}
                cancellingId={cancellingId}
                onBrowseMenu={() => setTab("menu")}
              />
            </div>
          )}
        </main>
      </div>

      {/* Call staff FAB (R7.1) */}
      {!isSessionEnded && <CallStaffButton onCall={handleCallStaff} />}

      {/* Bottom bar: running subtotal + cart */}
      <div className="qo-bottombar fixed inset-x-0 bottom-0 z-40">
        <div className="mx-auto flex max-w-lg items-center justify-between gap-3 px-4 py-3">
          <div className="min-w-0">
            <p className="qo-muted text-[11px] font-medium uppercase tracking-wide">
              Tạm tính đã gọi
            </p>
            <p className="qo-accent text-lg font-bold">
              {formatPrice(orderedSubtotal, currency)}
            </p>
          </div>

          {!isSessionEnded && (
            <button
              onClick={() => setCartOpen(true)}
              disabled={cart.totalItems === 0}
              className="qo-btn-primary flex shrink-0 items-center gap-2 rounded-full px-5 py-2.5 font-bold transition-transform active:scale-95"
            >
              <span>Giỏ hàng</span>
              {cart.totalItems > 0 && (
                <span className="qo-count-on-amber flex h-6 min-w-[1.5rem] items-center justify-center rounded-full px-1.5 text-xs font-bold">
                  {cart.totalItems}
                </span>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Photo lightbox */}
      {zoomedItem && (
        <ImageLightbox
          item={{
            name: zoomedItem.name,
            description: zoomedItem.description,
            price: zoomedItem.price,
            imageUrl: zoomedItem.image_large_url ?? zoomedItem.image_url,
          }}
          currency={currency}
          onClose={() => setZoomedItem(null)}
        />
      )}

      {/* Cart modal */}
      {cartOpen && (
        <Cart
          items={cart.items}
          currency={currency}
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

function TabButton({
  active,
  onClick,
  label,
  badge,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  badge?: number;
}) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`flex flex-1 items-center justify-center gap-2 rounded-full px-4 py-2.5 text-sm font-bold transition-colors ${
        active ? "qo-tab-active" : "qo-tab"
      }`}
    >
      <span>{label}</span>
      {badge !== undefined && badge > 0 && (
        <span
          className={`flex h-5 min-w-[1.25rem] items-center justify-center rounded-full px-1.5 text-[11px] font-bold ${
            active ? "qo-count-on-amber" : "qo-count-on-dark"
          }`}
        >
          {badge}
        </span>
      )}
    </button>
  );
}
