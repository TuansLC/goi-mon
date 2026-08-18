import { useState } from "react";

interface Props {
  src: string | null;
  alt: string;
  /** Category name — decides which glyph the placeholder shows. */
  categoryName?: string;
  /** Tailwind size classes, e.g. "h-16 w-16". */
  className?: string;
  /** Intrinsic pixel size, set on the <img> to avoid layout shift. */
  size?: number;
  onClick?: () => void;
}

/**
 * Menu photo thumbnail with a graceful fallback.
 *
 * A restaurant will not have photographed every dish on day one, so a missing
 * (or broken) image renders an icon placeholder of the same footprint — the list
 * keeps its rhythm instead of looking half-broken.
 *
 * Images are lazy-loaded with explicit dimensions: guests are on mobile data and
 * a long menu should not fetch every photo up front.
 */
export default function ItemImage({
  src,
  alt,
  categoryName,
  className = "h-16 w-16",
  size = 128,
  onClick,
}: Props) {
  const [failed, setFailed] = useState(false);
  const showPlaceholder = !src || failed;

  const content = showPlaceholder ? (
    <div
      className="qo-thumb-placeholder flex h-full w-full items-center justify-center"
      aria-hidden="true"
    >
      <PlaceholderGlyph categoryName={categoryName} />
    </div>
  ) : (
    <img
      src={src}
      alt={alt}
      width={size}
      height={size}
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
      className="h-full w-full object-cover"
    />
  );

  // Only interactive when there is a real photo to enlarge.
  if (onClick && !showPlaceholder) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={`qo-thumb ${className} shrink-0 overflow-hidden rounded-xl transition-transform active:scale-95`}
        aria-label={`Xem ảnh ${alt}`}
      >
        {content}
      </button>
    );
  }

  return (
    <div
      className={`qo-thumb ${className} shrink-0 overflow-hidden rounded-xl`}
    >
      {content}
    </div>
  );
}

function PlaceholderGlyph({ categoryName }: { categoryName?: string }) {
  const isDrink = /uống|bia|nước|drink|beverage/i.test(categoryName ?? "");

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      className="h-6 w-6 opacity-70"
      viewBox="0 0 20 20"
      fill="currentColor"
    >
      {isDrink ? (
        <path d="M6 2h8a1 1 0 011 1v2a1 1 0 01-1 1h-.09l-.72 10.07A2 2 0 0111.2 18H8.8a2 2 0 01-1.99-1.86L6.09 6H6a1 1 0 01-1-1V3a1 1 0 011-1zm1.6 6l.63 8h3.54l.63-8H7.6z" />
      ) : (
        <path d="M3 8h14a1 1 0 011 1 8 8 0 01-4 6.93V17a1 1 0 01-1 1H7a1 1 0 01-1-1v-1.07A8 8 0 012 9a1 1 0 011-1zm3.4-5.2a1 1 0 011.4-.2c.5.37.8.9.9 1.47.08.5-.02.98-.2 1.4a1 1 0 01-1.83-.8c.05-.12.07-.24.05-.35-.02-.1-.06-.18-.12-.22a1 1 0 01-.2-1.3zm4 0a1 1 0 011.4-.2c.5.37.8.9.9 1.47.08.5-.02.98-.2 1.4a1 1 0 01-1.83-.8c.05-.12.07-.24.05-.35-.02-.1-.06-.18-.12-.22a1 1 0 01-.2-1.3z" />
      )}
    </svg>
  );
}
