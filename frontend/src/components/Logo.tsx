type LogoMarkProps = { className?: string };

const CHECK = "M12.5 20.5l5.5 5.5L33 9";

/**
 * The FitWise mark: a bumper plate with a check rising out of it (train, then make the right
 * call). Drawn for the iron brand bar: the check is cut out of the plate in `iron` so it reads
 * at favicon size too. Decorative; the wordmark next to it carries the name.
 * `public/favicon.svg` is the same drawing on an iron tile.
 */
export function LogoMark({ className = "size-10" }: LogoMarkProps) {
  return (
    <svg aria-hidden="true" viewBox="0 0 40 40" className={`shrink-0 ${className}`} fill="none">
      <circle cx="19" cy="21" r="11" className="stroke-plate" strokeWidth="4.5" />
      <circle cx="19" cy="21" r="2" className="fill-plate" />
      <g strokeLinecap="round" strokeLinejoin="round">
        <path d={CHECK} className="stroke-iron" strokeWidth="8.5" />
        <path d={CHECK} className="stroke-chalk" strokeWidth="4" />
      </g>
    </svg>
  );
}
