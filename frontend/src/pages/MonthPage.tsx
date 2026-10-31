import { useSignedInUser } from "../components/RequireAuth";
import { CalendarNav } from "../features/calendar/CalendarNav";
import { MonthView } from "../features/calendar/MonthView";
import { paths } from "../paths";

/** Month view (spec F9) of the signed-in athlete. */
export function MonthPage() {
  const me = useSignedInUser();
  return (
    <div className="max-w-[40rem]">
      <CalendarNav />
      <MonthView athleteId={me.id} timezone={me.timezone} monthPath={paths.month} weekPath={paths.week} />
    </div>
  );
}
