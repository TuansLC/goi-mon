import type { MenuItem, CartItem } from "../types";
import { formatPrice } from "../format";

interface Props {
  items: MenuItem[];
  currency: string;
  cartItems: CartItem[];
  onAddItem: (item: MenuItem) => void;
  onOpenImage: (item: MenuItem) => void;
}

/**
 * "Món đặc trưng" — a horizontally scrolled strip of large photos.
 *
 * This is where big imagery pays off: a few highlighted dishes at the top of the
 * screen. The main list below stays on compact thumbnails so a 40-item menu is
 * still quick to scan.
 *
 * Renders nothing unless the owner flagged items AND those items have photos —
 * a carousel of placeholders would be worse than no carousel.
 */
export default function FeaturedCarousel({
  items,
  currency,
  cartItems,
  onAddItem,
  onOpenImage,
}: Props) {
  const withPhotos = items.filter((i) => i.image_url);
  if (withPhotos.length === 0) return null;

  return (
    <section aria-label="Món đặc trưng">
      <h2 className="qo-accent mb-2.5 flex items-center gap-2 text-sm font-bold uppercase tracking-wide">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="h-4 w-4"
          viewBox="0 0 20 20"
          fill="currentColor"
          aria-hidden="true"
        >
          <path d="M10 1.5l2.47 5.01 5.53.8-4 3.9.94 5.5L10 14.1l-4.94 2.6.94-5.5-4-3.9 5.53-.8L10 1.5z" />
        </svg>
        Món đặc trưng
        <span className="qo-divider ml-1 h-px flex-1" aria-hidden="true" />
      </h2>

      {/* Snap scrolling keeps cards aligned when swiped on a phone. */}
      <div className="-mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-1">
        {withPhotos.map((item) => {
          const inCart = cartItems.find((c) => c.menu_item_id === item.id);
          const unavailable = !item.is_available;

          return (
            <article
              key={item.id}
              className="qo-card w-[230px] shrink-0 snap-start overflow-hidden rounded-2xl"
            >
              <button
                type="button"
                onClick={() => onOpenImage(item)}
                className="block w-full"
                aria-label={`Xem ảnh ${item.name}`}
              >
                <img
                  src={item.image_url!}
                  alt={item.name}
                  width={400}
                  height={260}
                  loading="lazy"
                  decoding="async"
                  className={`h-[130px] w-full object-cover ${
                    unavailable ? "opacity-50" : ""
                  }`}
                />
              </button>

              <div className="flex items-center gap-2 px-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold">{item.name}</p>
                  <p className="qo-accent text-sm font-bold">
                    {formatPrice(parseFloat(item.price), currency)}
                  </p>
                </div>

                {unavailable ? (
                  <span className="qo-chip-off shrink-0 rounded px-1.5 py-0.5 text-[11px] font-semibold">
                    Hết
                  </span>
                ) : (
                  <button
                    onClick={() => onAddItem(item)}
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
                    {inCart && inCart.quantity > 0 && (
                      <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-red-500 text-[11px] font-bold text-white">
                        {inCart.quantity}
                      </span>
                    )}
                  </button>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
