import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { apiError } from "./errors";
import { dropUserDataExceptMe, meQueryKey } from "./session";

/** `exportMyData`: the ZIP and the file name the server proposed. */
export async function fetchExport(): Promise<{ blob: Blob; filename: string }> {
  const { data, error, response } = await api.GET("/me/export", { parseAs: "blob" });
  if (data === undefined || !response.ok) throw apiError(response, error);
  const match = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") ?? "");
  return { blob: data as Blob, filename: match?.[1] ?? "fitwise-export.zip" };
}

/** Hands a blob to the browser as a file download. */
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function useExportData() {
  return useMutation({
    mutationFn: async () => {
      const { blob, filename } = await fetchExport();
      saveBlob(blob, filename);
    },
  });
}

/**
 * `deleteMe` (D48: POST with the password). On success the server cleared the cookie: leave for
 * sign-in first, then drop every cached query, like sign-out.
 */
export function useDeleteAccount(leave: () => Promise<void> | void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (password: string) => {
      const { response, error } = await api.POST("/me/delete", { body: { password } });
      if (!response.ok) throw apiError(response, error);
    },
    onSuccess: async () => {
      await leave();
      dropUserDataExceptMe(queryClient);
      await queryClient.resetQueries({ queryKey: meQueryKey });
    },
  });
}
