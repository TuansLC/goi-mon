import { useState } from "react";

interface CallStaffButtonProps {
  onCall: () => Promise<{ created: boolean; message?: string }>;
}

/**
 * Floating "Gọi nhân viên" button (R7.1).
 *
 * When pressed, calls the staff endpoint.
 * - 201 (created): show confirmation "Nhân viên đang tới!"
 * - 200 (cooldown): show soft message "Đã gửi yêu cầu, nhân viên đang tới"
 * - Error: show error briefly
 *
 * Visible at all times when session is open.
 */
export default function CallStaffButton({ onCall }: CallStaffButtonProps) {
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  const handleClick = async () => {
    if (loading) return;
    setLoading(true);
    setFeedback(null);

    try {
      const result = await onCall();
      if (result.created) {
        setFeedback("Nhân viên đang tới!");
      } else {
        setFeedback(result.message || "Đã gửi yêu cầu, nhân viên đang tới.");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Lỗi không xác định";
      setFeedback(msg);
    } finally {
      setLoading(false);
      // Auto-hide feedback after 3 seconds
      setTimeout(() => setFeedback(null), 3000);
    }
  };

  return (
    <div className="fixed bottom-20 right-4 z-50 flex flex-col items-end gap-2">
      {/* Feedback toast */}
      {feedback && (
        <div className="bg-gray-800 text-white text-xs px-3 py-2 rounded-lg shadow-lg max-w-[200px] text-center">
          {feedback}
        </div>
      )}

      {/* Call staff FAB */}
      <button
        onClick={handleClick}
        disabled={loading}
        className="flex items-center gap-2 bg-blue-500 hover:bg-blue-600 active:bg-blue-700 text-white font-medium text-sm px-4 py-3 rounded-full shadow-lg disabled:opacity-70 transition-colors"
        aria-label="Gọi nhân viên"
      >
        {loading ? (
          <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
        ) : (
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-4 w-4"
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path d="M10 2a6 6 0 00-6 6v3.586l-.707.707A1 1 0 004 14h12a1 1 0 00.707-1.707L16 11.586V8a6 6 0 00-6-6zM10 18a3 3 0 01-3-3h6a3 3 0 01-3 3z" />
          </svg>
        )}
        <span>Gọi nhân viên</span>
      </button>
    </div>
  );
}
