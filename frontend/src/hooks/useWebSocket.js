import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';

/**
 * Hook to manage WebSocket connection for build job updates
 * @param {number} buildJobId - The build job ID to subscribe to
 * @param {boolean} enabled - Whether the WebSocket should be active
 */
export function useWebSocket(buildJobId, enabled = true) {
  const queryClient = useQueryClient();
  const wsRef = useRef(null);

  useEffect(() => {
    // Don't connect if disabled, no ID, or ID is invalid
    if (!enabled || !buildJobId || buildJobId === 'undefined' || buildJobId === undefined) {
      return;
    }

    // Use ws:// for localhost, wss:// for production
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.hostname}:8000/ws/builds/${buildJobId}/`;

    console.log('[WebSocket] Connecting to:', wsUrl);

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('[WebSocket] Connected to build job', buildJobId);
    };

    ws.onmessage = async (event) => {
      try {
        const data = JSON.parse(event.data);
        console.log('[WebSocket] Received:', data);

        if (data.type === 'build_update') {
          console.log('[WebSocket] Refetching build and queue data...');
          // Refetch both queries immediately
          await Promise.all([
            queryClient.refetchQueries(['buildJob', buildJobId]),
            queryClient.refetchQueries(['build-queue', buildJobId])
          ]);
          console.log('[WebSocket] Refetch complete');
        } else if (data.type === 'queue_update') {
          console.log('[WebSocket] Refetching queue data for item:', data.data?.id);
          // Refetch queue immediately for queue item updates
          await queryClient.refetchQueries(['build-queue', buildJobId]);
          console.log('[WebSocket] Queue refetch complete');
        }
      } catch (error) {
        console.error('[WebSocket] Error parsing message:', error);
      }
    };

    ws.onerror = (error) => {
      console.error('[WebSocket] Error:', error);
    };

    ws.onclose = (event) => {
      console.log('[WebSocket] Disconnected:', event.code, event.reason);
    };

    // Cleanup on unmount
    return () => {
      if (ws.readyState === WebSocket.OPEN) {
        console.log('[WebSocket] Closing connection');
        ws.close();
      }
    };
  }, [buildJobId, enabled, queryClient]);

  return wsRef.current;
}
