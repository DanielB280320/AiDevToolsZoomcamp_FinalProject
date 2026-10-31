/** Client routes. Both roles land on Today after sign-in in M1 (#9). */
export const paths = {
  home: "/",
  signIn: "/sign-in",
  signUp: "/sign-up",
  today: "/today",
  week: "/week",
  month: "/month",
  body: "/body",
  plan: "/plan",
  progress: "/progress",
  sessionChart: (sessionId: string) => `/progress/session/${sessionId}`,
  sessionChartPattern: "/progress/session/:sessionId",
  workout: (sessionId: string) => `/workout/${sessionId}`,
  workoutPattern: "/workout/:sessionId",
  onboarding: "/onboarding",
} as const;
