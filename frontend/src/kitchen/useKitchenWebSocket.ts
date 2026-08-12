/**
 * Kitchen WebSocket hook with exponential backoff reconnection.
 * On reconnect, triggers a board resync via REST (R4.8).
 */

import { useEffect, useRef, useCallback } from "react";
import type { KitchenWsEvent } from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

function getWsBaseUrl(): string {
  if (BASE_URL) {
    return BASE_URL.replace(/^http/, "ws");
  }
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}`;
}

interface UseKitchenWebSocketOptions {
  ticket: string | null;
  enabled: boolean;
  onEvent: (event: KitchenWsEvent) => void;
  onReconnect: () => void;
}

export function useKitchenWebSocket({
  ticket,
  enabled,
  onEvent,
  onReconnect,
}: UseKitchenWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const onReconnectRef = useRef(onReconnect);
  onReconnectRef.current = onReconnect;
  const hasConnectedOnce = useRef(false);

  const connect = useCallback(() => {
    if (!ticket || !enabled) return;

    const wsUrl = `${getWsBaseUrl()}/ws/kitchen?ticket=${ticket}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      attemptRef.current = 0;
      if (hasConnectedOnce.current) {
        // Reconnect — resync from REST
        onReconnectRef.current();
      }
      hasConnectedOnce.current = true;
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as KitchenWsEvent;
        onEventRef.current(data);
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = () => {
      wsRef.current = null;
      // Exponential backoff: max 30s
      const delay = Math.min(1000 * 2 ** attemptRef.current, 30000);
      attemptRef.current += 1;
      reconnectTimerRef.current = setTimeout(() => {
        connect();
      }, delay);
    };

    ws.onerror = () => {
      // onclose fires after onerror
    };
  }, [ticket, enabled]);

  useEffect(() => {
    if (enabled && ticket) {
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
  }, [connect, enabled, ticket]);
}
