/**
 * CommandPoller — polls the backend for pending bridge commands.
 *
 * The DJ dashboard can queue commands (reset_decks, reconnect, restart) via
 * POST /api/bridge/commands/{event_code}. This poller fetches them every 5s
 * and emits 'command' events for the bridge to act on.
 *
 * Respects the circuit breaker — skips polls when the backend is unreachable.
 */
import { EventEmitter } from "events";

import type { CircuitBreaker } from "./circuit-breaker.js";
import type { Logger } from "./logger.js";

const POLL_INTERVAL_MS = 5_000;
const FETCH_TIMEOUT_MS = 10_000;

export interface BridgeCommand {
  readonly command_id: string;
  readonly command_type: string;
  readonly payload?: Record<string, unknown>;
}

/**
 * Polls GET /api/bridge/commands/{event_code} for pending commands.
 *
 * Events emitted:
 *   'command' — fired for each command received, with the command type string
 *               and the full command payload as the second argument
 */
export class CommandPoller extends EventEmitter {
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private apiUrl = "";
  private apiKey = "";
  private eventCode = "";
  private readonly circuitBreaker: CircuitBreaker;
  private readonly log: Logger;

  constructor(circuitBreaker: CircuitBreaker, log: Logger) {
    super();
    this.circuitBreaker = circuitBreaker;
    this.log = log;
  }

  get isPolling(): boolean {
    return this.pollTimer !== null;
  }

  start(apiUrl: string, apiKey: string, eventCode: string): void {
    if (this.pollTimer !== null) {
      return;
    }

    this.apiUrl = apiUrl;
    this.apiKey = apiKey;
    this.eventCode = eventCode;

    this.log.info("Command poller started");
    this.pollTimer = setInterval(() => {
      this.poll();
    }, POLL_INTERVAL_MS);
  }

  stop(): void {
    if (this.pollTimer !== null) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
      this.log.info("Command poller stopped");
    }
  }

  private async poll(): Promise<void> {
    if (!this.circuitBreaker.allowRequest()) {
      this.log.debug("Command poll skipped — circuit breaker not allowing requests");
      return;
    }

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

      try {
        const response = await fetch(
          `${this.apiUrl}/api/bridge/commands/${this.eventCode}`,
          {
            method: "GET",
            headers: {
              "X-Bridge-API-Key": this.apiKey,
            },
            signal: controller.signal,
          },
        );

        if (!response.ok) {
          const text = await response.text();
          throw new Error(`HTTP ${response.status}: ${text}`);
        }

        this.circuitBreaker.recordSuccess();

        const body = (await response.json()) as { commands: BridgeCommand[] };
        for (const cmd of body.commands) {
          this.log.info(`Received command: ${cmd.command_type}`);
          this.emit("command", cmd.command_type, cmd);
        }
      } finally {
        clearTimeout(timeoutId);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      this.log.warn(`Command poll failed: ${message}`);
    }
  }
}
