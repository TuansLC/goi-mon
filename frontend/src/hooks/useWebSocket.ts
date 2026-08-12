import { useEffect, useRef, useCallback } from "react";
import type { WsEvent } from "../types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

/**
 * Derive the WebSocket URL from the REST API base URL.
 * E.g., "http://localhost:8000" → "ws://localhost:8000"
 *        "" (relative) → use window.location
 */
function getWsBaseUrl(): string {
  if (BASE_URL) {
    return BASE_URL.replace(/^http/, "ws");
  }
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}`;
}

interface UseWebSocketOptions {
  /** QR token for the customer WS endpoint */
  qrToken: string | undefined;
  /** Whether to connect (e.g., after session data is loaded) */
  enabled: boolean;
  /** Minimum seq to accept (events with seq <= this are discarded) */
  minSeq: number;
  /** Callback when a valid event is received */
  onEvent: (event: WsEvent) => void;
}

/**
 * Custom hook for customer WebSocket connection (R4.2, R4.8, R5.7).
 *
 * - Connects after initial session data is loaded from REST
 * - Reconnects automatically on disconnect with exponential backoff
 * - Filters events with seq <= minSeq (anti-stale)
 * - Dispatches valid events via onEvent callback
 */
export function useWebSocket({
  qrToken,
  enabled,
  minSeq,
  onEvent,
}: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const lastSeqRef = useRef(minSeq);
  // Keep onEvent stable reference
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  // Update lastSeq when minSeq changes (e.g., after resync)
  useEffect(() => {
    lastSeqRef.current = minSeq;
  }, [minSeq]);

  const connect = useCallback(() => {
    if (!qrToken || !enabled) return;

    const wsUrl = `${getWsBaseUrl()}/ws/t/${qrToken}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      attemptRef.current = 0;
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as WsEvent;
        // Anti-stale filtering: discard events with seq <= last known
        if (data.seq && data.seq <= lastSeqRef.current) {
          return;
        }
        // Update last known seq
        if (data.seq) {
          lastSeqRef.current = data.seq;
        }
        onEventRef.current(data);
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = () => {
      wsRef.current = null;
      // Reconnect with exponential backoff (max 30s)
      const delay = Math.min(1000 * 2 ** attemptRef.current, 30000);
      attemptRef.current += 1;
      reconnectTimerRef.current = setTimeout(() => {
        connect();
      }, delay);
    };

    ws.onerror = () => {
      // onclose will fire after onerror, triggering reconnect
    };
  }, [qrToken, enabled]);

  useEffect(() => {
    if (enabled && qrToken) {
      connect();
    }

    return () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect, enabled, qrToken]);
}
