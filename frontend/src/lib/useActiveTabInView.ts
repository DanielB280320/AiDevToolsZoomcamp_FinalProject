import { useEffect, useRef } from "react";
import { useLocation } from "react-router";

/**
 * For a tab strip that scrolls sideways without a scrollbar: keeps the current tab
 * (`aria-current="page"`) visible by scrolling the strip itself, never the page.
 */
export function useActiveTabInView() {
  const strip = useRef<HTMLUListElement>(null);
  const { pathname } = useLocation();
  useEffect(() => {
    const list = strip.current;
    const active = list?.querySelector<HTMLElement>('[aria-current="page"]');
    if (!list || !active) return;
    const left = active.offsetLeft - list.offsetLeft;
    if (left < list.scrollLeft) list.scrollLeft = left;
    else if (left + active.offsetWidth > list.scrollLeft + list.clientWidth) list.scrollLeft = left + active.offsetWidth - list.clientWidth;
  }, [pathname]);
  return strip;
}
