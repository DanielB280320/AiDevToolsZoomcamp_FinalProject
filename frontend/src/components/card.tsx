import type { ReactNode } from "react";

/**
 * The one card (D111): white surface, 1 px `line` border, 12 px radius, 16 px padding and the light
 * `shadow-card`, which is what separates it from the white page.
 * Every titled section and every standalone chart block is a card. Spacing between cards
 * (`mt-6`/`mt-8`) is added where it is used. `CARD_FLUSH` is the same card without padding, for a block
 * that sets its own (the month grid).
 */
export const CARD_FLUSH = "min-w-0 rounded-card border border-line bg-card shadow-card";
export const CARD = `${CARD_FLUSH} p-4`;

/**
 * A card that opens something (a day, a client, a session, a notification): border and fill react to
 * hover and press. Cards that do nothing on click do not use it. Flush: the row inside sets its own padding.
 */
export const CARD_LINK = `${CARD_FLUSH} card-link`;

/**
 * A figure inside a section card: a soft `well` fill (a step darker than the page, so it reads on
 * the white card), not a second bordered card
 * (no card inside a card).
 */
export const TILE = "min-w-0 rounded-card bg-well p-3";

/**
 * A repeated item inside a section card (an exercise, a meal, a version): a hairline outline only, so
 * there is no second card surface inside the card.
 */
export const ITEM = "rounded-control border border-line p-3";

/**
 * Expanding content: always in the DOM (hidden only while closed), so keyboard users and tests never
 * wait on the animation; it fades and grows in when it opens.
 */
export function Collapse({ id, open, children }: { id: string; open: boolean; children: ReactNode }) {
  return (
    <div id={id} hidden={!open} className="expand-in">
      <div>{children}</div>
    </div>
  );
}
