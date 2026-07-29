import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AIUsagePanel } from "./AIUsagePanel";

const usage = {
  summary: {
    calls: 12,
    input_units: 4200,
    output_units: 900,
    known_cost_usd: 0.0432,
    unknown_cost_calls: 3,
    denied_calls: 2,
    failed_calls: 1,
  },
  providers: [
    {
      provider: "openai",
      model: "gpt-4o-mini-2024-07-18",
      operation: "chat",
      calls: 8,
      p95_ms: 1820,
      known_cost_usd: 0.0432,
      unknown_cost_calls: 0,
    },
  ],
  purposes: [
    {
      purpose: "agent.parser",
      calls: 5,
      p95_ms: 1510,
      known_cost_usd: 0.012,
      denied_calls: 0,
      failed_calls: 1,
    },
  ],
  top_queries: [],
};

describe("AIUsagePanel", () => {
  it("shows cost coverage and the provider and purpose breakdowns", () => {
    render(
      <MemoryRouter>
        <AIUsagePanel usage={usage} />
      </MemoryRouter>,
    );

    expect(screen.getAllByText("$0.0432").length).toBeGreaterThan(0);
    expect(screen.getByText(/3 calls have unknown cost/i)).toBeInTheDocument();
    expect(screen.getByText("gpt-4o-mini-2024-07-18")).toBeInTheDocument();
    expect(screen.getByText("agent.parser")).toBeInTheDocument();
  });
});
