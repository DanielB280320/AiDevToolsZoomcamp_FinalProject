/** Client routes. Both roles land on Today after sign-in in M1 (#9). */
export const paths = {
  home: "/",
  signIn: "/sign-in",
  signUp: "/sign-up",
  today: "/today",
  /** The athlete's own view of one day (a note's day, F16). */
  day: (date: string) => `/today?date=${date}`,
  week: "/week",
  month: "/month",
  body: "/body",
  plan: "/plan",
  progress: "/progress",
  notifications: "/notifications",
  coach: "/coach",
  coachClients: "/coach/clients",
  /** A client's views in the coach context (F16); `tail` is `/week`, `/plan`, ... */
  coachClient: (athleteId: string, tail = "") => `/coach/clients/${athleteId}${tail}`,
  coachClientPattern: "/coach/clients/:athleteId",
  sessionChart: (sessionId: string) => `/progress/session/${sessionId}`,
  sessionChartPattern: "/progress/session/:sessionId",
  workout: (sessionId: string) => `/workout/${sessionId}`,
  workoutPattern: "/workout/:sessionId",
  onboarding: "/onboarding",
} as const;
