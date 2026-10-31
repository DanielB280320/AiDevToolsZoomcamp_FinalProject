import { useNavigate } from "react-router";

import { type AppNotification, useMarkNotificationRead } from "../../api/notifications";
import { targetOf } from "./model";

/** Open (mark read, then go to the target) and dismiss (mark read only), shared by the inbox and banners. */
export function useNotificationActions() {
  const navigate = useNavigate();
  const markRead = useMarkNotificationRead();
  const open = (notification: AppNotification) => {
    const target = targetOf(notification);
    const go = () => {
      if (target) void navigate(target);
    };
    if (notification.read_at) return go();
    markRead.mutate(notification.id, { onSuccess: go });
  };
  const dismiss = (notification: AppNotification) => markRead.mutate(notification.id);
  return { open, dismiss, isError: markRead.isError, isPending: markRead.isPending };
}
