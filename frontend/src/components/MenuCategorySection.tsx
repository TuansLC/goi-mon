import type { MenuCategory, MenuItem, CartItem } from "../types";

interface Props {
  category: MenuCategory;
  onAddItem: (item: MenuItem) => void;
  cartItems: CartItem[];
}

export default function MenuCategorySection({
  category,
  onAddItem,
  cartItems,
}: Props) {
  return (
    <section>
      <h2 className="text-base font-bold text-gray-800 mb-3 border-l-4 border-orange-400 pl-3">
        {category.name}
      </h2>
      <div className="space-y-2">
        {category.items.map((item) => {
          const inCart = cartItems.find((c) => c.menu_item_id === item.id);
          return (
            <MenuItemCard
              key={item.id}
              item={item}
              quantityInCart={inCart?.quantity ?? 0}
              onAdd={() => onAddItem(item)}
            />
          );
        })}
      </div>
    </section>
  );
}

interface MenuItemCardProps {
  item: MenuItem;
  quantityInCart: number;
  onAdd: () => void;
}

function MenuItemCard({ item, quantityInCart, onAdd }: MenuItemCardProps) {
  const price = parseFloat(item.price);
  const unavailable = !item.is_available;

  return (
    <div
      className={`flex items-center justify-between p-3 bg-white rounded-lg border ${
        unavailable ? "opacity-60 border-gray-200" : "border-gray-100 shadow-sm"
      }`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-gray-900 truncate">
            {item.name}
          </span>
          {unavailable && (
            <span className="shrink-0 text-xs bg-red-100 text-red-600 px-1.5 py-0.5 rounded font-medium">
              Hết hàng
            </span>
          )}
        </div>
        {item.description && (
          <p className="text-xs text-gray-500 mt-0.5 truncate">
            {item.description}
          </p>
        )}
        <p className="text-sm font-semibold text-orange-600 mt-1">
          {price.toLocaleString("vi-VN")}đ
        </p>
      </div>

      <div className="ml-3 shrink-0">
        {unavailable ? (
          <div className="w-9 h-9" />
        ) : (
          <button
            onClick={onAdd}
            className="relative w-9 h-9 flex items-center justify-center bg-orange-500 hover:bg-orange-600 text-white rounded-full transition-colors"
            aria-label={`Thêm ${item.name} vào giỏ`}
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-5 w-5"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path
                fillRule="evenodd"
                d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z"
                clipRule="evenodd"
              />
            </svg>
            {quantityInCart > 0 && (
              <span className="absolute -top-1 -right-1 bg-red-500 text-white text-xs w-5 h-5 flex items-center justify-center rounded-full font-bold">
                {quantityInCart}
              </span>
            )}
          </button>
        )}
      </div>
    </div>
  );
}
