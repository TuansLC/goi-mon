/**
 * StaffCallNotification — shows incoming staff calls from WebSocket.
 * Displays table label and ack button.
 */

import type { StaffCall } from "./types";

interface StaffCallNotificationProps {
  calls: StaffCall[];
  onAck: (callId: string) => void;
}

export default function StaffCallNotification({
  calls,
  onAck,
}: StaffCallNotificationProps) {
  if (calls.length === 0) return null;

  return (
    <div className="fixed top-4 right-4 z-50 space-y-2 max-w-sm">
      {calls.map((call) => (
        <div
          key={call.id}
          className="bg-purple-800 border border-purple-600 rounded-xl p-4 shadow-lg animate-blink-medium"
        >
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-white font-bold text-sm">
                🔔 Gọi nhân viên
              </p>
              <p className="text-purple-200 text-xs mt-0.5">
                {call.table_label || `Bàn ${call.table_id.slice(0, 6)}`}
              </p>
            </div>
            <button
              onClick={() => onAck(call.id)}
              className="py-2 px-4 rounded-lg bg-green-600 hover:bg-green-700 text-white font-semibold text-sm transition-colors whitespace-nowrap"
            >
              ✅ Nhận
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
