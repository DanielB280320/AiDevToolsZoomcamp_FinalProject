import { useSignedInUser } from "../components/RequireAuth";
import { CalendarNav } from "../features/calendar/CalendarNav";
import { WeekView } from "../features/calendar/WeekView";
import { paths } from "../paths";

/** Week view (spec F9) of the signed-in athlete. */
export function WeekPage() {
  const me = useSignedInUser();
  return (
    <div className="max-w-[40rem]">
      <CalendarNav />
      <WeekView athleteId={me.id} timezone={me.timezone} basePath={paths.week} />
    </div>
  );
}
