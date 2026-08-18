import type { MenuCategory, MenuItem, CartItem } from "../types";
import { formatPrice } from "../format";
import ItemImage from "./ItemImage";

interface Props {
  category: MenuCategory;
  currency: string;
  onAddItem: (item: MenuItem) => void;
  onOpenImage: (item: MenuItem) => void;
  cartItems: CartItem[];
}

export default function MenuCategorySection({
  category,
  currency,
  onAddItem,
  onOpenImage,
  cartItems,
}: Props) {
  return (
    <section>
      <h2 className="qo-accent mb-2.5 flex items-center gap-2 text-sm font-bold uppercase tracking-wide">
        <CategoryIcon name={category.name} />
        {category.name}
        <span className="qo-divider ml-1 h-px flex-1" aria-hidden="true" />
      </h2>
      <div className="space-y-2">
        {category.items.map((item) => {
          const inCart = cartItems.find((c) => c.menu_item_id === item.id);
          return (
            <MenuItemCard
              key={item.id}
              item={item}
              currency={currency}
              categoryName={category.name}
              quantityInCart={inCart?.quantity ?? 0}
              onAdd={() => onAddItem(item)}
              onOpenImage={() => onOpenImage(item)}
            />
          );
        })}
      </div>
    </section>
  );
}

/** Drink categories get a cup glyph, everything else a bowl (name heuristic). */
function CategoryIcon({ name }: { name: string }) {
  const isDrink = /uống|bia|nước|drink|beverage/i.test(name);

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      className="h-4 w-4"
      viewBox="0 0 20 20"
      fill="currentColor"
      aria-hidden="true"
    >
      {isDrink ? (
        <path d="M6 2h8a1 1 0 011 1v2a1 1 0 01-1 1h-.09l-.72 10.07A2 2 0 0111.2 18H8.8a2 2 0 01-1.99-1.86L6.09 6H6a1 1 0 01-1-1V3a1 1 0 011-1zm1.6 6l.63 8h3.54l.63-8H7.6z" />
      ) : (
        <path d="M3 8h14a1 1 0 011 1 8 8 0 01-4 6.93V17a1 1 0 01-1 1H7a1 1 0 01-1-1v-1.07A8 8 0 012 9a1 1 0 011-1zm3.4-5.2a1 1 0 011.4-.2c.5.37.8.9.9 1.47.08.5-.02.98-.2 1.4a1 1 0 01-1.83-.8c.05-.12.07-.24.05-.35-.02-.1-.06-.18-.12-.22a1 1 0 01-.2-1.3zm4 0a1 1 0 011.4-.2c.5.37.8.9.9 1.47.08.5-.02.98-.2 1.4a1 1 0 01-1.83-.8c.05-.12.07-.24.05-.35-.02-.1-.06-.18-.12-.22a1 1 0 01-.2-1.3z" />
      )}
    </svg>
  );
}

interface MenuItemCardProps {
  item: MenuItem;
  currency: string;
  categoryName: string;
  quantityInCart: number;
  onAdd: () => void;
  onOpenImage: () => void;
}

function MenuItemCard({
  item,
  currency,
  categoryName,
  quantityInCart,
  onAdd,
  onOpenImage,
}: MenuItemCardProps) {
  const price = parseFloat(item.price);
  const unavailable = !item.is_available;

  return (
    <div
      className={`flex items-center gap-3 rounded-xl p-3 ${
        unavailable ? "qo-card-off opacity-70" : "qo-card"
      }`}
    >
      <ItemImage
        src={item.image_url}
        alt={item.name}
        categoryName={categoryName}
        onClick={onOpenImage}
      />

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate font-semibold">{item.name}</span>
          {/* Sold-out items stay listed, just not orderable (R3.2). */}
          {unavailable && (
            <span className="qo-chip-off shrink-0 rounded px-1.5 py-0.5 text-[11px] font-semibold">
              Hết hàng
            </span>
          )}
        </div>

        {item.description && (
          <p className="qo-muted mt-0.5 truncate text-xs">{item.description}</p>
        )}

        <p className="qo-accent mt-1 text-sm font-bold">
          {formatPrice(price, currency)}
        </p>
      </div>

      {!unavailable && (
        <button
          onClick={onAdd}
          className="qo-btn-add relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-transform active:scale-95"
          aria-label={`Thêm ${item.name} vào giỏ`}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-5 w-5"
            viewBox="0 0 20 20"
            fill="currentColor"
            aria-hidden="true"
          >
            <path
              fillRule="evenodd"
              d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z"
              clipRule="evenodd"
            />
          </svg>
          {quantityInCart > 0 && (
            <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-red-500 text-[11px] font-bold text-white">
              {quantityInCart}
            </span>
          )}
        </button>
      )}
    </div>
  );
}
