import { useState } from "react";

interface CallStaffButtonProps {
  onCall: () => Promise<{ created: boolean; message?: string }>;
}

/**
 * Floating "Gọi nhân viên" button (R7.1).
 *
 * - 201 (created): "Nhân viên đang tới!"
 * - 200 (cooldown, R7.4): soft message from the server
 * - Error: show the message briefly
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
      setFeedback(
        result.created
          ? "Nhân viên đang tới!"
          : result.message || "Đã gửi yêu cầu, nhân viên đang tới."
      );
    } catch (err: unknown) {
      setFeedback(err instanceof Error ? err.message : "Lỗi không xác định");
    } finally {
      setLoading(false);
      setTimeout(() => setFeedback(null), 3000);
    }
  };

  return (
    <div className="fixed bottom-24 right-4 z-50 flex flex-col items-end gap-2">
      {feedback && (
        <div
          role="status"
          className="qo-notice max-w-[210px] rounded-xl px-3 py-2 text-center text-xs shadow-lg"
        >
          {feedback}
        </div>
      )}

      <button
        onClick={handleClick}
        disabled={loading}
        className="qo-btn-ghost flex items-center gap-2 rounded-full px-4 py-3 text-sm font-semibold shadow-lg transition-transform active:scale-95 disabled:opacity-70"
        aria-label="Gọi nhân viên"
      >
        {loading ? (
          <span className="qo-spinner h-4 w-4 animate-spin rounded-full" />
        ) : (
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="qo-accent h-4 w-4"
            viewBox="0 0 20 20"
            fill="currentColor"
            aria-hidden="true"
          >
            <path d="M10 1a7 7 0 00-7 7v1.5A2.5 2.5 0 001.5 12v1A2.5 2.5 0 004 15.5h.5a1 1 0 001-1V10a1 1 0 00-1-1H5V8a5 5 0 1110 0v1h-.5a1 1 0 00-1 1v4.5a1 1 0 001 1h.29A2.5 2.5 0 0113.5 17H11a1 1 0 100 2h2.5A4.5 4.5 0 0018 14.5V8a7 7 0 00-7-7h-1z" />
          </svg>
        )}
        <span>Gọi nhân viên</span>
      </button>
    </div>
  );
}
