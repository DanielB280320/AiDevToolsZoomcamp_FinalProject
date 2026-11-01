import { useOutletContext } from "react-router";

import type { UnitSystem } from "../../lib/units";

/** The client a coach is looking at: every request in the coach context uses `athleteId`, never `me`. */
export interface ClientScope {
  athleteId: string;
  displayName: string;
  units: UnitSystem;
  timezone: string;
}

/** The client of the surrounding `CoachClientShell`. */
export function useClientScope(): ClientScope {
  return useOutletContext<ClientScope>();
}
