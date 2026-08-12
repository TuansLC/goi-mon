import type { SessionItem } from "../types";

interface OrderStatusPanelProps {
  items: SessionItem[];
  onCancelItem: (itemId: string) => void;
  cancellingId: string | null;
}

/**
 * Displays all order items from the current session with their status (R4.2, R5.7).
 *
 * Customer sees only:
 * - "Đang chờ" for pending/cooking/ready
 * - "Đã ra" for served
 * - "Đã huỷ" for cancelled (with strikethrough)
 *
 * NO blinking/urgency indicators for customer (R5.7).
 * Pending items have a cancel button (R11.2).
 */
export default function OrderStatusPanel({
  items,
  onCancelItem,
  cancellingId,
}: OrderStatusPanelProps) {
  if (items.length === 0) {
    return null;
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border p-4">
      <h2 className="text-base font-bold text-gray-900 mb-3">
        Món đã gọi
      </h2>
      <ul className="space-y-2">
        {items.map((item) => (
          <OrderItemRow
            key={item.id}
            item={item}
            onCancel={() => onCancelItem(item.id)}
            cancelling={cancellingId === item.id}
          />
        ))}
      </ul>
    </div>
  );
}

function OrderItemRow({
  item,
  onCancel,
  cancelling,
}: {
  item: SessionItem;
  onCancel: () => void;
  cancelling: boolean;
}) {
  const isCancelled = item.status === "cancelled";
  const isServed = item.status === "served";
  const isPending = item.status === "pending";

  const statusLabel = isCancelled
    ? "Đã huỷ"
    : isServed
      ? "Đã ra"
      : "Đang chờ";

  const statusColor = isCancelled
    ? "text-red-500"
    : isServed
      ? "text-green-600"
      : "text-orange-500";

  return (
    <li
      className={`flex items-center justify-between py-2 border-b border-gray-100 last:border-b-0 ${
        isCancelled ? "opacity-60" : ""
      }`}
    >
      <div className="flex-1 min-w-0">
        <p
          className={`text-sm font-medium text-gray-800 ${
            isCancelled ? "line-through" : ""
          }`}
        >
          {item.name_snapshot}
          {item.quantity > 1 && (
            <span className="text-gray-500 ml-1">x{item.quantity}</span>
          )}
        </p>
        {item.note && (
          <p className="text-xs text-gray-400 truncate">{item.note}</p>
        )}
      </div>

      <div className="flex items-center gap-2 ml-2">
        <span className={`text-xs font-medium ${statusColor}`}>
          {statusLabel}
        </span>

        {/* Cancel button for pending items only (R11.2) */}
        {isPending && (
          <button
            onClick={onCancel}
            disabled={cancelling}
            className="text-xs text-red-400 hover:text-red-600 border border-red-200 rounded px-2 py-0.5 disabled:opacity-50 transition-colors"
            aria-label={`Huỷ ${item.name_snapshot}`}
          >
            {cancelling ? "..." : "Huỷ"}
          </button>
        )}
      </div>
    </li>
  );
}
