import type { RouteObject } from "react-router";

import { AppShell } from "./components/AppShell";
import { RequireAuth } from "./components/RequireAuth";
import { HomePage } from "./pages/HomePage";
import { MonthPage } from "./pages/MonthPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { OnboardingPage } from "./pages/OnboardingPage";
import { SignInPage } from "./pages/SignInPage";
import { SignUpPage } from "./pages/SignUpPage";
import { TodayPage } from "./pages/TodayPage";
import { WeekPage } from "./pages/WeekPage";
import { paths } from "./paths";

/** All routes render inside the shared shell (header, content, footer). */
export const routes: RouteObject[] = [
  {
    element: <AppShell />,
    children: [
      { index: true, element: <HomePage /> },
      { path: paths.signIn, element: <SignInPage /> },
      { path: paths.signUp, element: <SignUpPage /> },
      {
        // Signed-in pages: `GET /me` must succeed, a 401 redirects to sign-in.
        element: <RequireAuth />,
        children: [
          { path: paths.today, element: <TodayPage /> },
          { path: paths.week, element: <WeekPage /> },
          { path: paths.month, element: <MonthPage /> },
          { path: paths.onboarding, element: <OnboardingPage /> },
        ],
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
