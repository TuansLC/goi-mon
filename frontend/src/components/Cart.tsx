import type { CartItem } from "../types";
import { formatPrice } from "../format";

interface Props {
  items: CartItem[];
  currency: string;
  onClose: () => void;
  onUpdateQuantity: (menuItemId: string, quantity: number) => void;
  onUpdateNote: (menuItemId: string, note: string) => void;
  onRemoveItem: (menuItemId: string) => void;
  onSubmit: () => void;
  submitting: boolean;
  totalAmount: number;
}

export default function Cart({
  items,
  currency,
  onClose,
  onUpdateQuantity,
  onUpdateNote,
  onRemoveItem,
  onSubmit,
  submitting,
  totalAmount,
}: Props) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col">
      <div
        className="absolute inset-0 bg-black/60"
        onClick={onClose}
        aria-hidden="true"
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-label="Giỏ hàng"
        className="qo-page relative mt-auto flex max-h-[85vh] flex-col rounded-t-2xl shadow-2xl"
      >
        <div className="qo-header flex items-center justify-between rounded-t-2xl px-4 py-3">
          <h2 className="text-lg font-bold">Giỏ hàng</h2>
          <button
            onClick={onClose}
            className="qo-muted p-1 transition-colors hover:opacity-80"
            aria-label="Đóng giỏ hàng"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-6 w-6"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
          {items.map((item) => (
            <CartItemRow
              key={item.menu_item_id}
              item={item}
              currency={currency}
              onUpdateQuantity={onUpdateQuantity}
              onUpdateNote={onUpdateNote}
              onRemove={onRemoveItem}
            />
          ))}
        </div>

        <div className="qo-bottombar space-y-3 px-4 py-3">
          <div className="flex items-center justify-between text-base font-bold">
            <span>Tổng cộng</span>
            <span className="qo-accent">
              {formatPrice(totalAmount, currency)}
            </span>
          </div>
          <button
            onClick={onSubmit}
            disabled={submitting || items.length === 0}
            className="qo-btn-primary w-full rounded-xl py-3 font-bold transition-transform active:scale-[0.99] disabled:cursor-not-allowed"
          >
            {submitting ? "Đang gửi..." : "Gửi order"}
          </button>
        </div>
      </div>
    </div>
  );
}

interface CartItemRowProps {
  item: CartItem;
  currency: string;
  onUpdateQuantity: (menuItemId: string, quantity: number) => void;
  onUpdateNote: (menuItemId: string, note: string) => void;
  onRemove: (menuItemId: string) => void;
}

function CartItemRow({
  item,
  currency,
  onUpdateQuantity,
  onUpdateNote,
  onRemove,
}: CartItemRowProps) {
  const subtotal = item.price * item.quantity;

  return (
    <div className="qo-card flex flex-col gap-2 rounded-xl px-3 py-3">
      <div className="flex items-center justify-between">
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold">{item.name}</p>
          <p className="qo-muted text-sm">
            {formatPrice(item.price, currency)} × {item.quantity} ={" "}
            <span className="qo-accent-soft font-semibold">
              {formatPrice(subtotal, currency)}
            </span>
          </p>
        </div>

        <div className="ml-2 flex items-center gap-1">
          <button
            onClick={() =>
              onUpdateQuantity(item.menu_item_id, item.quantity - 1)
            }
            className="qo-btn-ghost flex h-8 w-8 items-center justify-center rounded-full"
            aria-label={`Giảm số lượng ${item.name}`}
          >
            −
          </button>
          <span className="w-7 text-center text-sm font-semibold">
            {item.quantity}
          </span>
          <button
            onClick={() =>
              onUpdateQuantity(item.menu_item_id, item.quantity + 1)
            }
            className="qo-btn-ghost flex h-8 w-8 items-center justify-center rounded-full"
            aria-label={`Tăng số lượng ${item.name}`}
          >
            +
          </button>
          <button
            onClick={() => onRemove(item.menu_item_id)}
            className="ml-1 flex h-8 w-8 items-center justify-center text-red-400 transition-colors hover:text-red-300"
            aria-label={`Xóa ${item.name} khỏi giỏ`}
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-4 w-4"
              viewBox="0 0 20 20"
              fill="currentColor"
              aria-hidden="true"
            >
              <path
                fillRule="evenodd"
                d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z"
                clipRule="evenodd"
              />
            </svg>
          </button>
        </div>
      </div>

      {/* Per-item note (R3.5) */}
      <input
        type="text"
        value={item.note}
        onChange={(e) => onUpdateNote(item.menu_item_id, e.target.value)}
        placeholder="Ghi chú (vd: ít đá, không hành...)"
        aria-label={`Ghi chú cho ${item.name}`}
        className="qo-input w-full rounded-lg px-3 py-2 text-sm"
      />
    </div>
  );
}
