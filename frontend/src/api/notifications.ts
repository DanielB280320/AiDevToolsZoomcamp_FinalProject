import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas } from "./client";
import { apiError } from "./errors";
import { meQueryKey } from "./session";

export type AppNotification = Schemas["Notification"];
export type NotificationType = Schemas["NotificationType"];

export const notificationsKey = ["notifications"] as const;
const PAGE_SIZE = 20;

async function fetchPage(opts: { unreadOnly: boolean; cursor?: string; limit: number; signal?: AbortSignal }) {
  const { data, error, response } = await api.GET("/notifications", {
    params: { query: { unread_only: opts.unreadOnly || undefined, limit: opts.limit, cursor: opts.cursor } },
    signal: opts.signal,
  });
  if (data) return data;
  throw apiError(response, error);
}

/** The inbox, newest first, paged with `next_cursor` (`listNotifications`, F17.2). */
export function useNotificationInbox() {
  return useInfiniteQuery({
    queryKey: [...notificationsKey, "inbox"],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => fetchPage({ unreadOnly: false, cursor: pageParam, limit: PAGE_SIZE, signal }),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

/** Unread notifications, for the Today banners (D79.3). */
export function useUnreadNotifications() {
  return useQuery({
    queryKey: [...notificationsKey, "unread"],
    queryFn: ({ signal }) => fetchPage({ unreadOnly: true, limit: PAGE_SIZE, signal }),
  });
}

/** Read state changes the lists and the bell count (`Me.unread_notification_count`). */
function useRefreshAfterRead() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: notificationsKey });
    void queryClient.invalidateQueries({ queryKey: meQueryKey });
  };
}

export function useMarkNotificationRead() {
  const refresh = useRefreshAfterRead();
  return useMutation({
    mutationFn: async (id: string) => {
      const { data, error, response } = await api.POST("/notifications/{notification_id}/read", {
        params: { path: { notification_id: id } },
      });
      if (data) return data;
      throw apiError(response, error);
    },
    onSettled: refresh,
  });
}

export function useMarkAllNotificationsRead() {
  const refresh = useRefreshAfterRead();
  return useMutation({
    mutationFn: async () => {
      const { data, error, response } = await api.POST("/notifications/read-all");
      if (data) return data;
      throw apiError(response, error);
    },
    onSettled: refresh,
  });
}
