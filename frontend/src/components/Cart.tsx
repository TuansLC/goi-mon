import type { CartItem } from "../types";

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
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <div className="relative mt-auto bg-white rounded-t-2xl max-h-[85vh] flex flex-col shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b">
          <h2 className="text-lg font-bold text-gray-900">Giỏ hàng</h2>
          <button
            onClick={onClose}
            className="p-1 text-gray-500 hover:text-gray-700"
            aria-label="Đóng giỏ hàng"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-6 w-6"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
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

        {/* Items */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
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

        {/* Footer */}
        <div className="border-t px-4 py-3 space-y-3">
          <div className="flex justify-between text-base font-bold">
            <span>Tổng cộng</span>
            <span className="text-orange-600">
              {formatPrice(totalAmount, currency)}
            </span>
          </div>
          <button
            onClick={onSubmit}
            disabled={submitting || items.length === 0}
            className="w-full bg-orange-500 hover:bg-orange-600 disabled:bg-gray-300 disabled:cursor-not-allowed text-white font-semibold py-3 rounded-xl transition-colors"
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
    <div className="flex flex-col gap-2 pb-3 border-b border-gray-100 last:border-0">
      <div className="flex items-center justify-between">
        <div className="flex-1 min-w-0">
          <p className="font-medium text-gray-900 truncate">{item.name}</p>
          <p className="text-sm text-gray-500">
            {formatPrice(item.price, currency)} × {item.quantity} ={" "}
            <span className="font-medium text-gray-700">
              {formatPrice(subtotal, currency)}
            </span>
          </p>
        </div>

        <div className="flex items-center gap-1 ml-2">
          <button
            onClick={() =>
              onUpdateQuantity(item.menu_item_id, item.quantity - 1)
            }
            className="w-7 h-7 flex items-center justify-center rounded-full border border-gray-300 text-gray-600 hover:bg-gray-100"
            aria-label="Giảm số lượng"
          >
            −
          </button>
          <span className="w-7 text-center text-sm font-medium">
            {item.quantity}
          </span>
          <button
            onClick={() =>
              onUpdateQuantity(item.menu_item_id, item.quantity + 1)
            }
            className="w-7 h-7 flex items-center justify-center rounded-full border border-gray-300 text-gray-600 hover:bg-gray-100"
            aria-label="Tăng số lượng"
          >
            +
          </button>
          <button
            onClick={() => onRemove(item.menu_item_id)}
            className="ml-1 w-7 h-7 flex items-center justify-center text-red-400 hover:text-red-600"
            aria-label="Xóa món"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-4 w-4"
              viewBox="0 0 20 20"
              fill="currentColor"
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

      {/* Note input */}
      <input
        type="text"
        value={item.note}
        onChange={(e) => onUpdateNote(item.menu_item_id, e.target.value)}
        placeholder="Ghi chú (vd: ít đá, không hành...)"
        className="w-full text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:border-orange-400 placeholder:text-gray-400"
      />
    </div>
  );
}

function formatPrice(amount: number, currency: string): string {
  if (currency === "VND") {
    return amount.toLocaleString("vi-VN") + "đ";
  }
  return amount.toLocaleString() + " " + currency;
}
