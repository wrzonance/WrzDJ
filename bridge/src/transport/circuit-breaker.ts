/**
 * Simple circuit breaker for backend API communication.
 *
 * States:
 *   CLOSED  — normal operation, requests flow through
 *   OPEN    — backend assumed down, requests short-circuited for cooldown period
 *   HALF_OPEN — one probe request allowed to test recovery
 *
 * Transitions:
 *   CLOSED → OPEN: after `failureThreshold` consecutive full-retry failures
 *   OPEN → HALF_OPEN: after `cooldownMs` elapses
 *   HALF_OPEN → CLOSED: probe request succeeds
 *   HALF_OPEN → OPEN: probe request fails (resets cooldown)
 */
import { TypedEventEmitter } from "../shared/typed-event-emitter.js";

export type CircuitState = "CLOSED" | "OPEN" | "HALF_OPEN";
export interface CircuitBreakerEventMap {
  stateChange: [change: { from: CircuitState; to: CircuitState }];
}

export interface CircuitRequestAdmission {
  readonly id: number;
  readonly generation: number;
  readonly state: "CLOSED" | "HALF_OPEN";
}

export interface CircuitBreakerConfig {
  /** Number of consecutive failures before opening the circuit (default: 3) */
  readonly failureThreshold?: number;
  /** Milliseconds to wait in OPEN state before attempting a probe (default: 60000) */
  readonly cooldownMs?: number;
}

const DEFAULT_FAILURE_THRESHOLD = 3;
const DEFAULT_COOLDOWN_MS = 60_000;

/**
 * CircuitBreaker tracks consecutive API failures and short-circuits
 * requests when the backend appears unreachable.
 *
 * Events:
 *   'stateChange' - emitted with { from, to } when circuit state changes
 */
export class CircuitBreaker extends TypedEventEmitter<CircuitBreakerEventMap> {
  private state: CircuitState = "CLOSED";
  private consecutiveFailures = 0;
  private lastFailureTime = 0;
  private probeInFlight = false;
  private nextAdmissionId = 0;
  private generation = 0;
  private activeProbeId: number | null = null;
  private readonly failureThreshold: number;
  private readonly cooldownMs: number;

  constructor(config?: CircuitBreakerConfig) {
    super();
    this.failureThreshold = config?.failureThreshold ?? DEFAULT_FAILURE_THRESHOLD;
    this.cooldownMs = config?.cooldownMs ?? DEFAULT_COOLDOWN_MS;
  }

  /** Current circuit state. */
  getState(): CircuitState {
    return this.state;
  }

  /** Number of consecutive failures recorded. */
  getConsecutiveFailures(): number {
    return this.consecutiveFailures;
  }

  /** Admit a request and retain the state it observed for completion accounting. */
  beginRequest(): CircuitRequestAdmission | null {
    if (this.state === "CLOSED") {
      return { id: ++this.nextAdmissionId, generation: this.generation, state: "CLOSED" };
    }

    if (this.state === "OPEN") {
      const elapsed = Date.now() - this.lastFailureTime;
      if (elapsed >= this.cooldownMs) {
        this.transitionTo("HALF_OPEN");
        // This first request IS the probe — mark in-flight
        return this.startProbe();
      }
      return null;
    }

    // HALF_OPEN — only one probe at a time
    if (this.probeInFlight) {
      return null;
    }
    return this.startProbe();
  }

  /** Record a successful request. Resets failure count and closes circuit. */
  recordSuccess(admission: CircuitRequestAdmission): void {
    if (!this.isCurrentAdmission(admission)) return;
    this.consecutiveFailures = 0;
    this.probeInFlight = false;
    this.activeProbeId = null;
    if (this.state !== "CLOSED") {
      this.transitionTo("CLOSED");
    }
  }

  /** Record a failed request. Increments failure count and may open circuit. */
  recordFailure(admission: CircuitRequestAdmission): void {
    if (!this.isCurrentAdmission(admission)) return;
    this.consecutiveFailures++;
    this.lastFailureTime = Date.now();
    this.probeInFlight = false;
    this.activeProbeId = null;

    if (this.state === "HALF_OPEN") {
      this.transitionTo("OPEN");
      return;
    }

    if (this.state === "CLOSED" && this.consecutiveFailures >= this.failureThreshold) {
      this.transitionTo("OPEN");
    }
  }

  /** Reset the circuit breaker to its initial state. */
  reset(): void {
    this.consecutiveFailures = 0;
    this.lastFailureTime = 0;
    this.probeInFlight = false;
    this.activeProbeId = null;
    if (this.state !== "CLOSED") {
      this.transitionTo("CLOSED");
    } else {
      this.generation++;
    }
  }

  private transitionTo(newState: CircuitState): void {
    const from = this.state;
    this.state = newState;
    this.generation++;
    this.emit("stateChange", { from, to: newState });
  }

  private startProbe(): CircuitRequestAdmission {
    const admission = {
      id: ++this.nextAdmissionId,
      generation: this.generation,
      state: "HALF_OPEN" as const,
    };
    this.probeInFlight = true;
    this.activeProbeId = admission.id;
    return admission;
  }

  private isCurrentAdmission(admission: CircuitRequestAdmission): boolean {
    if (admission.generation !== this.generation) return false;
    if (admission.state === "CLOSED") return this.state === "CLOSED";
    return this.state === "HALF_OPEN" && this.activeProbeId === admission.id;
  }
}
