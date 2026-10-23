import type { ReactNode } from "react";
import { Link } from "react-router";

interface AuthLayoutProps {
  title: string;
  lead: string;
  switchPrompt: string;
  switchLink: string;
  switchTo: string;
  children: ReactNode;
}

/**
 * Sign-in and sign-up share this frame: one column on phones; from `lg` the heading sits beside
 * the form so the form stays at a comfortable reading width.
 */
export function AuthLayout({ title, lead, switchPrompt, switchLink, switchTo, children }: AuthLayoutProps) {
  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,30rem)] lg:gap-16">
      <div className="lg:pt-2">
        <h1 className="font-display text-step-4 font-bold text-balance sm:text-step-5">{title}</h1>
        <p className="mt-3 max-w-[34ch] text-step-1 text-slate">{lead}</p>
      </div>
      <div>
        {children}
        <p className="mt-8 border-t border-line pt-6">
          {switchPrompt}{" "}
          <Link to={switchTo} className="font-semibold text-spruce underline underline-offset-4 hover:text-spruce-dark">
            {switchLink}
          </Link>
        </p>
      </div>
    </div>
  );
}
