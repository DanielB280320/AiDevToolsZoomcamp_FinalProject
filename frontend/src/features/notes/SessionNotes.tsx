import { useTranslation } from "react-i18next";

import { useDay } from "../../api/calendar";
import { useSessionChart } from "../../api/charts";
import { useCachedMe } from "../../api/session";
import { exerciseNotes, NoteThread, sessionNotes } from "./NoteThread";

/**
 * Coach notes of one session in the session view: the note on the session, then the notes on each
 * of its exercises. A coach can add to them; the athlete only reads.
 */
export function SessionNotes({ athleteId, sessionId }: { athleteId: string; sessionId: string }) {
  const { t } = useTranslation();
  // Not `useSignedInUser`: inside a coach client view the outlet context is the client's scope.
  const me = useCachedMe();
  const chart = useSessionChart(athleteId, sessionId);
  const day = useDay(athleteId, chart.data?.date);
  if (!chart.data || !day.data) return null;
  const notes = day.data.notes;
  return (
    <section aria-labelledby="session-notes" className="mt-6">
      <h2 id="session-notes" className="font-display text-step-2 font-bold">
        {t("notes.sessionTitle")}
      </h2>
      <NoteThread
        athleteId={athleteId}
        notes={sessionNotes(notes)}
        target={{ scope: "session", session_id: sessionId }}
        label={t("notes.sessionLabel")}
      />
      {chart.data.exercises.map((entry) => {
        const own = exerciseNotes(notes, entry.exercise.id);
        if (own.length === 0 && me?.role !== "coach") return null;
        return (
          <div key={entry.exercise.id} className="mt-4">
            <h3 className="font-semibold">{entry.exercise.name}</h3>
            <NoteThread
              athleteId={athleteId}
              notes={own}
              target={{ scope: "exercise", exercise_id: entry.exercise.id, session_id: sessionId }}
              label={entry.exercise.name}
            />
          </div>
        );
      })}
    </section>
  );
}
