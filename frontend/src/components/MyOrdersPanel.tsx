import { useMemo, useState } from "react";
import type { SessionItem } from "../types";
import { formatPrice, formatTime } from "../format";

interface Props {
  items: SessionItem[];
  currency: string;
  onCancelItem: (itemId: string) => void;
  cancellingId: string | null;
  onBrowseMenu: () => void;
}

interface OrderRound {
  orderId: string;
  /** 1-based round number, stable even when a whole round is hidden. */
  number: number;
  at: string;
  items: SessionItem[];
}

/**
 * "Đơn của tôi" — every item of the current session, grouped by order round
 * ("Đợt 1", "Đợt 2"...) since one session can hold many orders (R3.4).
 *
 * Cancelled items are hidden behind a toggle so the list stays focused on what
 * is still coming. Customer-facing status is deliberately coarse (R4.2): only
 * "Đang chờ" and "Đã ra". The internal `cooking` / `ready` states stay on the
 * kitchen screen, so an item that can no longer be self-cancelled shows a hint
 * to ask staff rather than exposing that the kitchen already started it (R11.3).
 */
export default function MyOrdersPanel({
  items,
  currency,
  onCancelItem,
  cancellingId,
  onBrowseMenu,
}: Props) {
  const [showCancelled, setShowCancelled] = useState(false);

  const rounds = useMemo<OrderRound[]>(() => {
    const byOrder = new Map<string, SessionItem[]>();
    for (const item of items) {
      const bucket = byOrder.get(item.order_id);
      if (bucket) {
        bucket.push(item);
      } else {
        byOrder.set(item.order_id, [item]);
      }
    }

    return Array.from(byOrder.entries())
      .map(([orderId, roundItems]) => ({
        orderId,
        items: roundItems,
        at: roundItems.reduce(
          (earliest, i) => (i.requested_at < earliest ? i.requested_at : earliest),
          roundItems[0].requested_at
        ),
      }))
      .sort((a, b) => a.at.localeCompare(b.at))
      .map((round, index) => ({ ...round, number: index + 1 }));
  }, [items]);

  const cancelledCount = useMemo(
    () => items.filter((i) => i.status === "cancelled").length,
    [items]
  );

  // Drop cancelled items (and any round left empty) unless the toggle is on.
  const visibleRounds = useMemo<OrderRound[]>(() => {
    if (showCancelled) return rounds;
    return rounds
      .map((round) => ({
        ...round,
        items: round.items.filter((i) => i.status !== "cancelled"),
      }))
      .filter((round) => round.items.length > 0);
  }, [rounds, showCancelled]);

  if (rounds.length === 0) {
    return (
      <div className="py-14 text-center">
        <p className="font-medium">Chưa gọi món nào</p>
        <p className="qo-muted mt-1 text-sm">
          Chọn món ở tab “Gọi món” để bắt đầu.
        </p>
        <button
          onClick={onBrowseMenu}
          className="qo-accent mt-4 text-sm font-semibold underline underline-offset-4"
        >
          Xem menu
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {visibleRounds.length === 0 ? (
        <div className="py-10 text-center">
          <p className="font-medium">Không còn món nào đang chờ</p>
          <p className="qo-muted mt-1 text-sm">Các món trước đó đã huỷ.</p>
          <button
            onClick={onBrowseMenu}
            className="qo-accent mt-4 text-sm font-semibold underline underline-offset-4"
          >
            Gọi thêm món
          </button>
        </div>
      ) : (
        visibleRounds.map((round) => (
          <section key={round.orderId}>
            <div className="mb-2 flex items-center gap-3">
              <h3 className="qo-muted shrink-0 text-sm font-semibold">
                Đợt {round.number}
                <span className="font-normal"> · {formatTime(round.at)}</span>
              </h3>
              <span className="qo-divider h-px flex-1" aria-hidden="true" />
            </div>

            <ul className="space-y-2">
              {round.items.map((item) => (
                <OrderItemRow
                  key={item.id}
                  item={item}
                  currency={currency}
                  onCancel={() => onCancelItem(item.id)}
                  cancelling={cancellingId === item.id}
                />
              ))}
            </ul>
          </section>
        ))
      )}

      {cancelledCount > 0 && (
        <button
          onClick={() => setShowCancelled((v) => !v)}
          aria-expanded={showCancelled}
          className="qo-btn-ghost qo-muted w-full rounded-xl py-2.5 text-xs font-medium"
        >
          {showCancelled
            ? "Ẩn món đã huỷ"
            : `Hiện món đã huỷ (${cancelledCount})`}
        </button>
      )}
    </div>
  );
}

function OrderItemRow({
  item,
  currency,
  onCancel,
  cancelling,
}: {
  item: SessionItem;
  currency: string;
  onCancel: () => void;
  cancelling: boolean;
}) {
  const isCancelled = item.status === "cancelled";
  const isServed = item.status === "served";
  // Only a `pending` item can be cancelled by the customer (R11.2 / R11.3).
  const canSelfCancel = item.status === "pending";
  const needsStaffToCancel = !isServed && !isCancelled && !canSelfCancel;
  const unitPrice = parseFloat(item.price_snapshot);

  return (
    <li
      className={`qo-card flex items-center gap-3 rounded-xl px-3 py-2.5 ${
        isCancelled ? "opacity-55" : ""
      }`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p
            className={`truncate text-sm font-semibold ${
              isCancelled ? "line-through" : ""
            }`}
          >
            {item.name_snapshot}
          </p>
          {item.quantity > 1 && (
            <span className="qo-chip-qty shrink-0 rounded-md px-1.5 py-0.5 text-[11px] font-bold">
              x{item.quantity}
            </span>
          )}
        </div>

        {Number.isFinite(unitPrice) && (
          <p className="qo-muted mt-0.5 text-xs">
            {formatPrice(unitPrice, currency)} / phần
          </p>
        )}

        {item.note && (
          <p className="qo-muted mt-0.5 truncate text-xs italic">
            “{item.note}”
          </p>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <StatusBadge served={isServed} cancelled={isCancelled} />

        {canSelfCancel && (
          <button
            onClick={onCancel}
            disabled={cancelling}
            className="qo-btn-danger-ghost rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors disabled:opacity-50"
            aria-label={`Huỷ ${item.name_snapshot}`}
          >
            {cancelling ? "..." : "Huỷ"}
          </button>
        )}

        {needsStaffToCancel && (
          <span className="qo-muted max-w-[104px] text-right text-[11px] leading-tight">
            Gọi nhân viên nếu cần huỷ
          </span>
        )}
      </div>
    </li>
  );
}

function StatusBadge({
  served,
  cancelled,
}: {
  served: boolean;
  cancelled: boolean;
}) {
  if (cancelled) {
    return (
      <span className="qo-chip-cancelled rounded-full px-2.5 py-1 text-[11px] font-semibold">
        Đã huỷ
      </span>
    );
  }
  if (served) {
    return (
      <span className="qo-chip-served rounded-full px-2.5 py-1 text-[11px] font-semibold">
        Đã ra
      </span>
    );
  }
  return (
    <span className="qo-chip-wait rounded-full px-2.5 py-1 text-[11px] font-semibold">
      Đang chờ
    </span>
  );
}
