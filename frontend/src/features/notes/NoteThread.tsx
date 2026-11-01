import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { type CoachNote, type NoteInput, useCreateNote, useDeleteNote, useUpdateNote } from "../../api/notes";
import { useCachedMe } from "../../api/session";

const MAX = 2000;

/** Notes of a day view, split by what they refer to. */
export const dayNotes = (notes: CoachNote[]) => notes.filter((n) => n.scope === "day");
export const sessionNotes = (notes: CoachNote[]) => notes.filter((n) => n.scope === "session");
export const exerciseNotes = (notes: CoachNote[], exerciseId: string) =>
  notes.filter((n) => n.scope === "exercise" && n.exercise?.id === exerciseId);

/** What a new note refers to (the contract's `NoteInput` without the text). */
export type NoteTarget = Omit<NoteInput, "text">;

function Composer({ athleteId, target, label }: { athleteId: string; target: NoteTarget; label: string }) {
  const { t } = useTranslation();
  const id = useId();
  const [text, setText] = useState("");
  const create = useCreateNote(athleteId);
  const submit = () => {
    if (!text.trim() || create.isPending) return;
    create.mutate({ ...target, text: text.trim() }, { onSuccess: () => setText("") });
  };
  return (
    <form
      className="mt-2"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <label htmlFor={id} className="block text-step--1 font-semibold">
        {t("notes.add", { label })}
      </label>
      <textarea
        id={id}
        value={text}
        maxLength={MAX}
        rows={2}
        onChange={(e) => setText(e.target.value)}
        className="mt-1 w-full rounded-md border-2 border-iron p-2"
      />
      <button
        type="submit"
        aria-disabled={!text.trim() || create.isPending || undefined}
        className="mt-1 min-h-11 rounded-md bg-spruce px-4 font-semibold text-chalk hover:bg-spruce-dark aria-disabled:opacity-75"
      >
        {t("notes.save")}
      </button>
      {create.isError && (
        <p role="alert" className="mt-1 border-l-4 border-alert pl-3 text-alert">
          {t("notes.failed")}
        </p>
      )}
    </form>
  );
}

function NoteItem({ athleteId, note, canEdit }: { athleteId: string; note: CoachNote; canEdit: boolean }) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(note.text);
  const update = useUpdateNote(athleteId);
  const remove = useDeleteNote(athleteId);
  const editId = useId();
  return (
    <li data-testid="coach-note" className="border-l-4 border-plate py-1 pl-3">
      <p className="text-step--1 font-semibold text-slate">{t("notes.by", { name: note.author.display_name })}</p>
      {editing ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!text.trim()) return;
            update.mutate({ id: note.id, text: text.trim() }, { onSuccess: () => setEditing(false) });
          }}
        >
          <label htmlFor={editId} className="sr-only">
            {t("notes.editLabel")}
          </label>
          <textarea
            id={editId}
            value={text}
            maxLength={MAX}
            rows={2}
            onChange={(e) => setText(e.target.value)}
            className="w-full rounded-md border-2 border-iron p-2"
          />
          <button type="submit" className="min-h-11 rounded-md bg-spruce px-4 font-semibold text-chalk hover:bg-spruce-dark">
            {t("notes.save")}
          </button>
          <button
            type="button"
            onClick={() => {
              setText(note.text);
              setEditing(false);
            }}
            className="ml-2 min-h-11 px-3 font-semibold text-spruce underline underline-offset-4"
          >
            {t("notes.cancel")}
          </button>
          {update.isError && (
            <p role="alert" className="border-l-4 border-alert pl-3 text-alert">
              {t("notes.failed")}
            </p>
          )}
        </form>
      ) : (
        <p className="whitespace-pre-wrap break-words">{note.text}</p>
      )}
      {canEdit && !editing && (
        <p className="flex gap-4">
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="min-h-11 font-semibold text-spruce underline underline-offset-4"
          >
            {t("notes.edit")}
          </button>
          <button
            type="button"
            onClick={() => remove.mutate(note.id)}
            className="min-h-11 font-semibold text-alert underline underline-offset-4"
          >
            {t("notes.delete")}
          </button>
        </p>
      )}
      {remove.isError && (
        <p role="alert" className="border-l-4 border-alert pl-3 text-alert">
          {t("notes.failed")}
        </p>
      )}
    </li>
  );
}

/**
 * Coach notes on one target (F16): everyone who may see the view reads them; only a coach gets the
 * composer, and only the author gets edit and delete. Athletes never get a create control.
 * `label` names the target for assistive technology ("Day", the exercise's name, ...).
 */
export function NoteThread({
  athleteId,
  notes,
  target,
  label,
}: {
  athleteId: string;
  notes: CoachNote[];
  /** Where a new note goes; without it the thread is read-only. */
  target?: NoteTarget;
  label: string;
}) {
  const { t } = useTranslation();
  // Not `useSignedInUser`: inside a coach client view the outlet context is the client's scope.
  const me = useCachedMe();
  const canWrite = me?.role === "coach" && target !== undefined;
  if (notes.length === 0 && !canWrite) return null;
  return (
    <div className="mt-2" data-testid="note-thread">
      {notes.length > 0 && (
        <ul aria-label={t("notes.listLabel", { label })} className="space-y-2">
          {notes.map((note) => (
            <NoteItem key={note.id} athleteId={athleteId} note={note} canEdit={me?.role === "coach" && note.author.id === me.id} />
          ))}
        </ul>
      )}
      {canWrite && <Composer athleteId={athleteId} target={target} label={label} />}
    </div>
  );
}
