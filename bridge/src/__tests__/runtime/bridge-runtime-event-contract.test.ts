import { expect, it } from "vitest";
import type { BridgeRuntime } from "../../runtime/bridge-runtime.js";

function compileEventContract(runtime: BridgeRuntime): void {
  runtime.on("statusChanged", (snapshot) => {
    const isRunning: boolean = snapshot.running;
    void isRunning;
  });
  runtime.on("connection", (event) => {
    const connected: boolean = event.connected;
    void connected;
  });

  // Regression for 57cfcdc6867f: event consumers previously guessed listener payloads.
  // @ts-expect-error Unknown event names must be rejected by the shared runtime contract.
  runtime.on("connecton", () => {});
  // @ts-expect-error Listener payloads must match the runtime's emitted event shape.
  runtime.emit("connection", { connected: "yes" });
}

it("keeps BridgeRuntime event names and payloads compile-time checked", () => {
  expect(compileEventContract).toBeTypeOf("function");
});
