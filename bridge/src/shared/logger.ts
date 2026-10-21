/**
 * Structured logger for the WrzDJ bridge.
 *
 * Provides leveled logging (debug/info/warn/error) with ISO timestamps
 * and component tags. Outputs to console by default, but a global handler
 * can be set to intercept all log entries (e.g., for IPC forwarding or
 * file persistence in bridge-app).
 *
 * Usage:
 *   const log = new Logger("Bridge");
 *   log.info("Starting...");
 *   // → 2026-02-21T10:30:00.000Z [INFO] [Bridge] Starting...
 *
 *   log.warn("Retrying...");
 *   // → 2026-02-21T10:30:01.000Z [WARN] [Bridge] Retrying...
 */

export type LogLevel = "debug" | "info" | "warn" | "error";

export interface LogEntry {
  readonly timestamp: string;
  readonly level: LogLevel;
  readonly component: string;
  readonly message: string;
}

export type LogHandler = (entry: LogEntry) => void;

const LEVEL_PRIORITY: Readonly<Record<LogLevel, number>> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

let globalHandler: LogHandler | null = null;
let globalMinLevel: LogLevel = "info";

/** Set a global handler to intercept all log entries. Pass null to reset to console output. */
export function setLogHandler(handler: LogHandler | null): void {
  globalHandler = handler;
}

/** Set the minimum log level. Messages below this level are silently dropped. */
export function setMinLogLevel(level: LogLevel): void {
  globalMinLevel = level;
}

/** Get the current minimum log level. */
export function getMinLogLevel(): LogLevel {
  return globalMinLevel;
}

/** Get the current global log handler (for testing). */
export function getLogHandler(): LogHandler | null {
  return globalHandler;
}

/**
 * Format a LogEntry into a single-line string for console output.
 *
 * Format: `2026-02-21T10:30:00.000Z [LEVEL] [Component] message`
 */
export function formatLogEntry(entry: LogEntry): string {
  return `${entry.timestamp} [${entry.level.toUpperCase()}] [${entry.component}] ${entry.message}`;
}

export class Logger {
  constructor(private readonly component: string) {}

  debug(message: string): void {
    this.write("debug", message);
  }

  info(message: string): void {
    this.write("info", message);
  }

  warn(message: string): void {
    this.write("warn", message);
  }

  error(message: string): void {
    this.write("error", message);
  }

  /** Create a child logger with a sub-component prefix (e.g., "Bridge:API"). */
  child(subComponent: string): Logger {
    return new Logger(`${this.component}:${subComponent}`);
  }

  private write(level: LogLevel, message: string): void {
    if (LEVEL_PRIORITY[level] < LEVEL_PRIORITY[globalMinLevel]) return;

    const entry: LogEntry = {
      timestamp: new Date().toISOString(),
      level,
      component: this.component,
      message,
    };

    if (globalHandler) {
      globalHandler(entry);
      return;
    }

    // Default: write to console with appropriate method
    const formatted = formatLogEntry(entry);
    switch (level) {
      case "error":
        console.error(formatted);
        break;
      case "warn":
        console.warn(formatted);
        break;
      default:
        console.log(formatted);
        break;
    }
  }
}
