import { fireEvent, render, screen } from "@testing-library/react";
import { Line, LineChart, XAxis, YAxis } from "recharts";
import { describe, expect, it } from "vitest";

import { ChartTooltip, TOOLTIP_UNIT } from "../src/features/charts/ChartTooltip";

const rows = [
  { day: "a", done: 40 },
  { day: "b", done: 75 },
];

describe("ChartTooltip", () => {
  it("shows the hovered point's label, series name and value with its unit", async () => {
    const { container } = render(
      <LineChart width={320} height={200} data={rows}>
        <XAxis dataKey="day" />
        <YAxis />
        <ChartTooltip label={(day: string) => `Day ${day}`} unit={TOOLTIP_UNIT.percent} />
        <Line dataKey="done" name="Completion" isAnimationActive={false} />
      </LineChart>,
    );
    expect(screen.queryByText("Completion")).toBeNull();

    const chart = container.querySelector(".recharts-wrapper");
    expect(chart).not.toBeNull();
    fireEvent.mouseMove(chart as Element, { clientX: 300, clientY: 80 });

    expect(await screen.findByText("Day b")).toBeInTheDocument();
    const tooltip = container.querySelector(".recharts-tooltip-wrapper");
    expect(tooltip?.textContent).toContain("Completion");
    expect(tooltip?.textContent).toContain("75%");
  });
});
