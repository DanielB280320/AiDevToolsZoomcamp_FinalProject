import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, renderHook, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Collapse } from "../src/components/card";
import { CHART_ANIMATION_MS, useChartAnimation } from "../src/lib/motion";

function mockReducedMotion(reduce: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("prefers-reduced-motion") ? reduce : false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("chart animation (D111, AC9/AC10)", () => {
  it("animates every series briefly by default", () => {
    mockReducedMotion(false);
    const { result } = renderHook(() => useChartAnimation());
    expect(result.current.isAnimationActive).toBe(true);
    expect(result.current.animationDuration).toBeLessThanOrEqual(400);
    expect(result.current.animationDuration).toBe(CHART_ANIMATION_MS);
  });

  it("switches Recharts animation off with prefers-reduced-motion: reduce", () => {
    mockReducedMotion(true);
    const { result } = renderHook(() => useChartAnimation());
    expect(result.current.isAnimationActive).toBe(false);
  });

  it("falls back to animating when matchMedia is not available", () => {
    vi.stubGlobal("matchMedia", undefined);
    const { result } = renderHook(() => useChartAnimation());
    expect(result.current.isAnimationActive).toBe(true);
  });
});

describe("CSS motion under prefers-reduced-motion (AC10)", () => {
  const css = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");

  it("zeroes transitions and animations and drops the press scale", () => {
    const block = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
    expect(block).toContain("animation-duration: 0.01ms !important");
    expect(block).toContain("transition-duration: 0.01ms !important");
    expect(block).toContain("transform: none !important");
  });

  it("keeps the motion durations as tokens", () => {
    for (const token of ["--duration-press", "--duration-open", "--duration-fill", "--ease-soft"]) {
      expect(css).toContain(`${token}:`);
    }
  });
});

describe("Collapse (AC8)", () => {
  it("keeps the content in the DOM, hidden only while closed, and shows it at once when opened", () => {
    const { rerender } = render(
      <Collapse id="panel" open={false}>
        <button type="button">inside</button>
      </Collapse>,
    );
    const panel = document.getElementById("panel");
    expect(panel).toHaveAttribute("hidden");
    expect(screen.getByText("inside", { selector: "button" })).toBeInTheDocument();
    rerender(
      <Collapse id="panel" open>
        <button type="button">inside</button>
      </Collapse>,
    );
    expect(panel).not.toHaveAttribute("hidden");
    expect(screen.getByRole("button", { name: "inside" })).toBeVisible();
  });
});
