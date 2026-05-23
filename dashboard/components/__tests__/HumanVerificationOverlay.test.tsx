import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { createRef } from "react";
import HumanVerificationOverlay from "../HumanVerificationOverlay";

describe("HumanVerificationOverlay", () => {
  it("renders the LoadingPanel while state=loading", () => {
    const ref = createRef<HTMLDivElement>();
    render(
      <HumanVerificationOverlay state="loading" widgetContainerRef={ref} onRetry={() => {}}>
        <div data-testid="hidden-child">child</div>
      </HumanVerificationOverlay>,
    );
    expect(screen.getByText(/just a moment/i)).toBeDefined();
    expect(screen.queryByTestId("hidden-child")).toBeNull();
  });

  it("renders the ChallengePanel when state=challenge with a visible widget container", () => {
    const ref = createRef<HTMLDivElement>();
    render(
      <HumanVerificationOverlay state="challenge" widgetContainerRef={ref} onRetry={() => {}}>
        <div data-testid="hidden-child">child</div>
      </HumanVerificationOverlay>,
    );
    expect(screen.getByText(/one more step/i)).toBeDefined();
    expect(screen.queryByTestId("hidden-child")).toBeNull();
    const container = screen.getByTestId("hv-widget-container");
    expect(container).toBeDefined();
    expect(container.style.opacity).toBe("1");
  });

  it("renders the FailedPanel and calls onRetry on button click", () => {
    const ref = createRef<HTMLDivElement>();
    const onRetry = vi.fn();
    render(
      <HumanVerificationOverlay state="failed" widgetContainerRef={ref} onRetry={onRetry}>
        <div data-testid="hidden-child">child</div>
      </HumanVerificationOverlay>,
    );
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("renders children only when state=verified", () => {
    const ref = createRef<HTMLDivElement>();
    render(
      <HumanVerificationOverlay state="verified" widgetContainerRef={ref} onRetry={() => {}}>
        <div data-testid="visible-child">visible</div>
      </HumanVerificationOverlay>,
    );
    expect(screen.getByTestId("visible-child")).toBeDefined();
    expect(screen.queryByText(/just a moment/i)).toBeNull();
  });

  it("attaches the widget ref in non-verified states", () => {
    const ref = createRef<HTMLDivElement>();
    render(
      <HumanVerificationOverlay state="loading" widgetContainerRef={ref} onRetry={() => {}}>
        <div>child</div>
      </HumanVerificationOverlay>,
    );
    expect(ref.current).not.toBeNull();
    expect(ref.current?.tagName).toBe("DIV");
  });
});
