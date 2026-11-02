import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, type Schemas } from "./client";
import { apiError } from "./errors";

export type WorkoutImportResult = Schemas["WorkoutImportResult"];

/** One rejected row: `rows.<n>` in the problem's `errors[]` (row 1 is the header). */
export interface ImportRowError {
  row: number | null;
  reason: string;
}

/** The row errors of a `422 invalid_import` problem (`fieldErrors` keyed by `rows.<n>`). */
export function rowErrors(fieldErrors: Record<string, string>): ImportRowError[] {
  return Object.entries(fieldErrors).map(([field, reason]) => {
    const match = /^rows\.(\d+)$/.exec(field);
    return { row: match ? Number(match[1]) : null, reason };
  });
}

/** `importWorkouts`: uploads the CSV as multipart `file`. */
export function useImportWorkouts() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (file: File): Promise<WorkoutImportResult> => {
      const { data, error, response } = await api.POST("/athletes/{athlete_id}/imports/workouts", {
        params: { path: { athlete_id: "me" } },
        // The generated type of a binary part is a string; the real body is the form below.
        body: { file: "" },
        bodySerializer: () => {
          const form = new FormData();
          form.append("file", file);
          return form;
        },
      });
      if (data) return data;
      throw apiError(response, error);
    },
    // Imported days change history, calendars, charts and energy balances.
    onSuccess: () => queryClient.invalidateQueries(),
  });
}
