import { useTranslation } from "react-i18next";
import { Navigate, Outlet, useOutletContext } from "react-router";

import { isUnauthenticated, type Me, useMe } from "../api/session";
import { paths } from "../paths";

/** Guards the signed-in pages with `GET /me`: 401 sends the visitor to sign-in. */
export function RequireAuth() {
  const { t } = useTranslation();
  const me = useMe();

  if (me.isPending) {
    return (
      <p role="status" className="text-step-1 text-slate">
        {t("session.checking")}
      </p>
    );
  }

  if (me.isError) {
    if (isUnauthenticated(me.error)) return <Navigate to={paths.signIn} replace />;
    return (
      <div role="alert" className="max-w-[38rem] border-l-4 border-alert pl-4">
        <p className="text-step-1 font-semibold">{t("session.loadFailed")}</p>
        <button
          type="button"
          onClick={() => void me.refetch()}
          className="mt-4 min-h-12 rounded-md bg-spruce px-5 py-3 font-semibold text-chalk hover:bg-spruce-dark"
        >
          {t("session.retry")}
        </button>
      </div>
    );
  }

  return <Outlet context={me.data satisfies Me} />;
}

/** The signed-in user, inside a route rendered by `RequireAuth`. */
export function useSignedInUser(): Me {
  return useOutletContext<Me>();
}
