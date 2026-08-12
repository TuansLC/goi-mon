/**
 * KitchenItemCard — displays a single kitchen board item with:
 * - Blinking animation based on overdue_level
 * - Mark served (✅) button
 * - Undo button (visible for 2 min after serving)
 * - Cancel button
 * - Status badge
 *
 * R5.1: Items with prep_time_snapshot=0 do NOT blink.
 */

import { useState, useEffect, useRef } from "react";

interface KitchenItemCardProps {
  id: string;
  name_snapshot: string;
  quantity: number;
  note: string | null;
  status: "pending" | "cooking" | "ready";
  requested_at: string;
  prep_time_snapshot: number;
  overdue_level: number | null;
  onMarkServed: (id: string) => void;
  onUndo: (id: string) => void;
  onCancel: (id: string) => void;
  /** If item was recently served (for undo tracking) */
  servedAt?: number | null;
}

function getBlinkClass(overdueLevel: number | null, prepTime: number): string {
  // R5.1: prep_time=0 → no blink
  if (prepTime === 0) return "";
  if (overdueLevel === null) return "";
  switch (overdueLevel) {
    case 0:
      return "animate-blink-slow"; // 1.5s
    case 1:
      return "animate-blink-medium"; // 1s
    case 2:
      return "animate-blink-fast"; // 0.6s
    case 3:
      return "animate-blink-fastest"; // 0.3s
    default:
      return "animate-blink-fastest";
  }
}

function getStatusBadge(status: string) {
  switch (status) {
    case "pending":
      return <span className="px-2 py-0.5 bg-yellow-600 text-yellow-100 text-xs rounded-full">Chờ</span>;
    case "cooking":
      return <span className="px-2 py-0.5 bg-orange-600 text-orange-100 text-xs rounded-full">Nấu</span>;
    case "ready":
      return <span className="px-2 py-0.5 bg-green-600 text-green-100 text-xs rounded-full">Sẵn</span>;
    default:
      return null;
  }
}

const UNDO_WINDOW_MS = 2 * 60 * 1000; // 2 minutes

export default function KitchenItemCard({
  id,
  name_snapshot,
  quantity,
  note,
  status,
  prep_time_snapshot,
  overdue_level,
  onMarkServed,
  onUndo,
  onCancel,
  servedAt,
}: KitchenItemCardProps) {
  const [showUndo, setShowUndo] = useState(false);
  const undoTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (servedAt) {
      const elapsed = Date.now() - servedAt;
      const remaining = UNDO_WINDOW_MS - elapsed;
      if (remaining > 0) {
        setShowUndo(true);
        undoTimerRef.current = setTimeout(() => setShowUndo(false), remaining);
      } else {
        setShowUndo(false);
      }
    } else {
      setShowUndo(false);
    }
    return () => {
      if (undoTimerRef.current) clearTimeout(undoTimerRef.current);
    };
  }, [servedAt]);

  const blinkClass = getBlinkClass(overdue_level, prep_time_snapshot);

  return (
    <div
      className={`bg-gray-800 border border-gray-700 rounded-xl p-4 relative ${blinkClass}`}
    >
      {/* Overdue indicator */}
      {prep_time_snapshot > 0 && overdue_level !== null && overdue_level > 0 && (
        <span className="absolute top-2 right-2 text-lg">🧨</span>
      )}

      {/* Header: name + quantity */}
      <div className="flex items-start justify-between mb-2">
        <div>
          <h3 className="text-white font-bold text-lg leading-tight">
            {name_snapshot}
          </h3>
          <p className="text-gray-400 text-sm">x{quantity}</p>
        </div>
        {getStatusBadge(status)}
      </div>

      {/* Note */}
      {note && (
        <p className="text-gray-400 text-sm italic mb-3 border-l-2 border-gray-600 pl-2">
          {note}
        </p>
      )}

      {/* Actions */}
      <div className="flex gap-2 mt-3">
        {!servedAt && (
          <>
            <button
              onClick={() => onMarkServed(id)}
              className="flex-1 py-2 px-3 rounded-lg bg-green-600 hover:bg-green-700 text-white font-semibold text-sm transition-colors"
              title="Đánh dấu đã phục vụ"
            >
              ✅ Xong
            </button>
            <button
              onClick={() => onCancel(id)}
              className="py-2 px-3 rounded-lg bg-red-700 hover:bg-red-800 text-white font-semibold text-sm transition-colors"
              title="Huỷ món"
            >
              ✕
            </button>
          </>
        )}
        {showUndo && servedAt && (
          <button
            onClick={() => onUndo(id)}
            className="flex-1 py-2 px-3 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-semibold text-sm transition-colors"
          >
            ↩ Hoàn tác
          </button>
        )}
      </div>
    </div>
  );
}
