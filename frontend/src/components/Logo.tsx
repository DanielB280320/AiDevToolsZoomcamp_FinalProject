type LogoMarkProps = { className?: string };

/**
 * The FitWise mark: the end of a loaded barbell seen from the side, three plates stepping up
 * along the bar, which also reads as a rising bar chart (train, and see the progress). Drawn
 * for the iron brand bar: `plate` plates on a `chalk` bar, plain shapes so it holds at favicon
 * size. Decorative; the wordmark next to it carries the name.
 * `public/favicon.svg` is the same drawing on an iron tile.
 */
export function LogoMark({ className = "size-10" }: LogoMarkProps) {
  return (
    <svg aria-hidden="true" viewBox="0 0 40 40" className={`shrink-0 ${className}`} fill="none">
      <path d="M4 20h32" className="stroke-chalk" strokeWidth="3.2" strokeLinecap="round" />
      <g className="fill-plate">
        <rect x="8" y="14" width="5" height="12" rx="1.8" />
        <rect x="15" y="9.5" width="5.5" height="21" rx="1.8" />
        <rect x="22.5" y="4.5" width="6.5" height="31" rx="2" />
      </g>
    </svg>
  );
}
