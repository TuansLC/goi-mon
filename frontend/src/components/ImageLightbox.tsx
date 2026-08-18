import { useEffect } from "react";
import { formatPrice } from "../format";

export interface LightboxItem {
  name: string;
  description: string | null;
  price: string;
  /** Large variant; falls back to the thumbnail when absent. */
  imageUrl: string | null;
}

interface Props {
  item: LightboxItem;
  currency: string;
  onClose: () => void;
}

/**
 * Full-screen photo view opened by tapping a menu thumbnail.
 *
 * Deliberately read-only — ordering happens from the list, so this stays a quick
 * "let me see the dish" detour that Esc / backdrop tap dismisses.
 */
export default function ImageLightbox({ item, currency, onClose }: Props) {
  // Esc to close, and prevent the page behind from scrolling while open.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Ảnh ${item.name}`}
      className="fixed inset-0 z-[60] flex items-center justify-center p-4"
    >
      <div
        className="absolute inset-0 bg-black/80"
        onClick={onClose}
        aria-hidden="true"
      />

      <div className="qo-page relative w-full max-w-md overflow-hidden rounded-2xl shadow-2xl">
        <button
          onClick={onClose}
          className="qo-btn-ghost absolute right-3 top-3 z-10 flex h-9 w-9 items-center justify-center rounded-full"
          aria-label="Đóng ảnh"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-5 w-5"
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

        {item.imageUrl && (
          <img
            src={item.imageUrl}
            alt={item.name}
            className="max-h-[60vh] w-full object-cover"
          />
        )}

        <div className="px-4 py-3">
          <div className="flex items-start justify-between gap-3">
            <h2 className="text-base font-bold">{item.name}</h2>
            <span className="qo-accent shrink-0 font-bold">
              {formatPrice(parseFloat(item.price), currency)}
            </span>
          </div>
          {item.description && (
            <p className="qo-muted mt-1 text-sm">{item.description}</p>
          )}
        </div>
      </div>
    </div>
  );
}
