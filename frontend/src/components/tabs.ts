/** Hairline under a tab strip (D111); add `no-scrollbar overflow-x-auto` where the strip scrolls on a phone. */
export const TAB_STRIP = "flex border-b border-line";

const TAB = "press flex min-h-12 items-center justify-center border-b-[3px] font-display text-step-1 font-semibold no-underline";

/** A tab: spruce text with a 3 px spruce underline when active, plain text with a hover tint otherwise. */
export function tabClass(active: boolean, extra = ""): string {
  const state = active ? "border-spruce text-spruce" : "border-transparent text-iron hover:bg-line/50 hover:text-spruce";
  return `${TAB} ${state} ${extra}`.trim();
}
