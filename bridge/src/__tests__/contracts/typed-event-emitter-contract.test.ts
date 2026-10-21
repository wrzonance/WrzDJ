import { describe, expect, it } from "vitest";
import type { DeckLiveEvent } from "../../deck/deck-state.js";
import type { DeckStateManager } from "../../deck/deck-state-manager.js";
import { CommandPoller, type BridgeCommand } from "../../transport/command-poller.js";
import type { CircuitBreaker } from "../../transport/circuit-breaker.js";
import { EventArgumentMap, TypedEventEmitter } from "../../shared/typed-event-emitter.js";

describe("typed bridge event contracts", () => {
  // Regression for 57cfcdc6867f: typed wrappers must preserve Node emitter behavior.
  it("preserves an array-valued payload as one emitted argument", () => {
    const emitter = new TypedEventEmitter<EventArgumentMap<{ tracks: string[] }>>();
    const received: unknown[][] = [];
    emitter.on("tracks", (...args) => received.push(args));

    emitter.emit("tracks", ["one", "two"]);

    expect(received).toEqual([[ ["one", "two"] ]]);
  });

  it("preserves listener order, one-time behavior, and removal aliases", () => {
    const emitter = new TypedEventEmitter<{ tick: [value: number] }>();
    const received: string[] = [];
    const ordinary = (value: number): void => { received.push(`on:${value}`); };
    const added = (value: number): void => { received.push(`add:${value}`); };
    const prepended = (value: number): void => { received.push(`prepend:${value}`); };

    emitter.on("tick", ordinary);
    emitter.addListener("tick", added);
    emitter.prependListener("tick", prepended);
    emitter.once("tick", (value) => { received.push(`once:${value}`); });
    emitter.prependOnceListener("tick", (value) => { received.push(`prepend-once:${value}`); });

    emitter.emit("tick", 1);
    emitter.removeListener("tick", ordinary);
    emitter.off("tick", added);
    emitter.emit("tick", 2);

    expect(received).toEqual([
      "prepend-once:1",
      "prepend:1",
      "on:1",
      "add:1",
      "once:1",
      "prepend:2",
    ]);
  });
});

declare const poller: CommandPoller;
declare const command: BridgeCommand;
declare const breaker: CircuitBreaker;
declare const manager: DeckStateManager;
declare const deckLive: DeckLiveEvent;
declare const legacyPayloadEmitter: TypedEventEmitter<EventArgumentMap<{ tracks: string[]; ready: void }>>;

if (false) {
  poller.emit("command", "reset_decks", command);
  poller.addListener("command", (type, receivedCommand) => void [type, receivedCommand.command_id]);
  poller.prependListener("command", (type, receivedCommand) => void [type, receivedCommand.command_id]);
  poller.prependOnceListener("command", (type, receivedCommand) => void [type, receivedCommand.command_id]);
  poller.removeListener("command", (type, receivedCommand) => void [type, receivedCommand.command_id]);
  poller.listeners("command");
  poller.rawListeners("command");
  poller.on("command", (type, receivedCommand) => {
    const commandType: string = type;
    const id: string = receivedCommand.command_id;
    void [commandType, id];
  });
  // @ts-expect-error the command event requires both emitted arguments
  poller.emit("command", "reset_decks");
  // @ts-expect-error command event arguments have fixed types
  poller.emit("command", command, "reset_decks");
  // @ts-expect-error authenticationError has no payload
  poller.emit("authenticationError", command);
  // @ts-expect-error undeclared poller events are rejected
  poller.emit("connected");
  // @ts-expect-error addListener must reject unknown event names
  poller.addListener("connected", () => {});
  // @ts-expect-error addListener must retain the command tuple
  poller.addListener("command", (commandId: number, eventType: boolean) => void [commandId, eventType]);
  // @ts-expect-error prependListener must reject unknown event names
  poller.prependListener("connected", () => {});
  // @ts-expect-error prependListener must retain the command tuple
  poller.prependListener("command", (commandId: number, eventType: boolean) => void [commandId, eventType]);
  // @ts-expect-error removeListener must reject unknown event names
  poller.removeListener("connected", () => {});
  // @ts-expect-error removeAllListeners must reject unknown event names
  poller.removeAllListeners("connected");
  // @ts-expect-error listenerCount must reject unknown event names
  poller.listenerCount("connected");
  // @ts-expect-error listeners must reject unknown event names
  poller.listeners("connected");
  // @ts-expect-error rawListeners must reject unknown event names
  poller.rawListeners("connected");

  breaker.emit("stateChange", { from: "OPEN", to: "CLOSED" });
  breaker.on("stateChange", ({ from }) => {
    const state: "CLOSED" | "OPEN" | "HALF_OPEN" = from;
    void state;
  });
  // @ts-expect-error circuit state changes require CircuitState values
  breaker.emit("stateChange", { from: "BROKEN", to: "CLOSED" });

  manager.emit("deckLive", deckLive);
  manager.emit("nowPlayingCleared");
  // @ts-expect-error nowPlayingCleared carries no payload
  manager.emit("nowPlayingCleared", deckLive);

  // Legacy payload maps keep array values as one payload argument.
  legacyPayloadEmitter.emit("tracks", ["one", "two"]);
  // @ts-expect-error array payloads are not spread into multiple event arguments
  legacyPayloadEmitter.emit("tracks", "one", "two");
}
