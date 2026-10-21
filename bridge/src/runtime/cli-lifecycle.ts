import type { BridgeRuntime } from "./bridge-runtime.js";
import { Logger } from "../shared/logger.js";

const log = new Logger("Bridge");

export interface CliSignalProcess {
  on(signal: "SIGINT" | "SIGTERM", handler: () => void): unknown;
  off(signal: "SIGINT" | "SIGTERM", handler: () => void): unknown;
  exitCode: NodeJS.Process["exitCode"];
}

interface CliShutdownHandlers {
  readonly runtime: Pick<BridgeRuntime, "stop">;
  readonly signalProcess: CliSignalProcess;
  onInterrupt: () => void;
  onTerminate: () => void;
}

function completeShutdown(error: unknown, signalProcess: CliSignalProcess): void {
  log.error(`Shutdown failed: ${error instanceof Error ? error.message : String(error)}`);
  signalProcess.exitCode = 1;
}

function finishShutdown(handlers: CliShutdownHandlers): void {
  handlers.signalProcess.off("SIGINT", handlers.onInterrupt);
  handlers.signalProcess.off("SIGTERM", handlers.onTerminate);
}

function shutdown(handlers: CliShutdownHandlers, signal: string): void {
  log.info(`Received ${signal}, shutting down...`);
  void handlers.runtime.stop().then(() => {
    handlers.signalProcess.exitCode = 0;
  }, (error: unknown) => completeShutdown(error, handlers.signalProcess))
    .finally(finishShutdown.bind(null, handlers));
}

/** Start a runtime and own process signal handlers until its shutdown completes. */
export async function startCli(
  runtime: Pick<BridgeRuntime, "start" | "stop">,
  signalProcess: CliSignalProcess = process,
): Promise<void> {
  const handlers: CliShutdownHandlers = {
    runtime,
    signalProcess,
    onInterrupt: () => {},
    onTerminate: () => {},
  };
  handlers.onInterrupt = shutdown.bind(null, handlers, "SIGINT");
  handlers.onTerminate = shutdown.bind(null, handlers, "SIGTERM");
  signalProcess.on("SIGINT", handlers.onInterrupt);
  signalProcess.on("SIGTERM", handlers.onTerminate);

  try {
    await runtime.start();
  } catch (error) {
    finishShutdown(handlers);
    throw error;
  }
}
