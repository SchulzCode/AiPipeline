import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";

const css = readFileSync(path.resolve(__dirname, "globals.css"), "utf8");

describe("globals.css motion policy", () => {
  it("defines a prefers-reduced-motion block that shortens animations rather than only disabling them selectively", () => {
    const match = css.match(/@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?)\n\}/);
    expect(match).not.toBeNull();
    const block = match![1];
    // Per Emil Kowalski's design-engineering skill: reduced motion means
    // fewer/gentler animations, not zero - so this must shorten/disable
    // movement globally, not just remove one specific animation.
    expect(block).toMatch(/animation-duration:\s*0\.01ms/);
    expect(block).toMatch(/transition-duration:\s*0\.01ms/);
  });

  it("defines the live-pulse and enter animation utilities used for active-state indicators", () => {
    expect(css).toMatch(/@keyframes aipipe-pulse/);
    expect(css).toMatch(/\.animate-live-pulse\s*\{/);
    expect(css).toMatch(/\.animate-enter\s*\{/);
  });

  it("keeps a visible focus ring for keyboard navigation", () => {
    expect(css).toMatch(/:focus-visible\s*\{[\s\S]*?outline:/);
  });
});
