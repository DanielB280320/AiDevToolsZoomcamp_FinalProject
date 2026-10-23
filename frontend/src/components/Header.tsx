import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";

import { useCachedMe, useSignOut } from "../api/session";
import { paths } from "../paths";

function SignOutButton() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const signOut = useSignOut(() => navigate(paths.signIn, { replace: true }));

  const onClick = () => {
    if (!signOut.isPending) signOut.mutate();
  };

  return (
    <div className="flex flex-col items-end">
      <button
        type="button"
        onClick={onClick}
        aria-disabled={signOut.isPending || undefined}
        aria-describedby={signOut.isError ? "sign-out-error" : undefined}
        className="min-h-11 rounded-md border-2 border-chalk/60 px-4 py-2 font-semibold text-chalk hover:border-chalk aria-disabled:opacity-75"
      >
        {signOut.isPending ? t("nav.signingOut") : t("nav.signOut")}
      </button>
      {signOut.isError && (
        <p id="sign-out-error" role="alert" className="mt-1 max-w-[24ch] text-right text-step--1 text-plate">
          {t("nav.signOutFailed")}
        </p>
      )}
    </div>
  );
}

export function Header() {
  const { t } = useTranslation();
  const me = useCachedMe();

  return (
    <header className="border-b-4 border-plate bg-iron text-chalk">
      <div className="mx-auto flex w-full max-w-5xl items-center justify-between gap-4 px-4 py-3 sm:px-8">
        <Link
          to={me ? paths.today : paths.home}
          aria-label={t("app.homeLink")}
          className="font-display text-step-3 font-bold leading-none tracking-tight text-chalk no-underline"
        >
          {t("app.name")}
        </Link>
        {/* Primary navigation (Today, Plan, Progress) lands here with those pages. */}
        {me && <SignOutButton />}
      </div>
    </header>
  );
}
