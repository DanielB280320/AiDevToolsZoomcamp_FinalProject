import { Navigate, useParams } from "react-router";

import { useSignedInUser } from "../components/RequireAuth";
import { WorkoutScreen } from "../features/workout/WorkoutScreen";
import { paths } from "../paths";

/** `/workout/:sessionId` (spec F10): the athlete's live workout screen. */
export function WorkoutPage() {
  const me = useSignedInUser();
  const { sessionId } = useParams();
  // Coaches cannot log sets (F16.4); the screen is for the athlete's own sessions.
  if (!sessionId || me.role !== "athlete") return <Navigate to={paths.today} replace />;
  return <WorkoutScreen me={me} sessionId={sessionId} />;
}
