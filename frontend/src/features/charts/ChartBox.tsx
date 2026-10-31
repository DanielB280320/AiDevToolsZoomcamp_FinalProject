import type { ReactElement } from "react";
import { ResponsiveContainer } from "recharts";

/**
 * Fixed-height, full-width chart area. `min-w-0` lets it shrink inside flex/grid parents so a 360 px
 * screen never scrolls sideways; the initial size is a first-paint fallback that the container
 * replaces as soon as it measures itself.
 */
export function ChartBox({
  label,
  height = 220,
  children,
}: {
  label: string;
  height?: number;
  children: ReactElement;
}) {
  return (
    <div role="img" aria-label={label} className="w-full min-w-0 max-w-full overflow-hidden" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 320, height }}>
        {children}
      </ResponsiveContainer>
    </div>
  );
}
