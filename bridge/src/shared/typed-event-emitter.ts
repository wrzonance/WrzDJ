import { EventEmitter } from "node:events";

/** Convert the existing one-payload event maps without spreading array payloads. */
export type EventArgumentMap<Payloads extends object> = {
  [Name in keyof Payloads]: Payloads[Name] extends void ? [] : [payload: Payloads[Name]];
};

/** EventEmitter whose events map directly to their emitted argument tuples. */
export class TypedEventEmitter<Events extends { [Name in keyof Events]: unknown[] }> extends EventEmitter {
  emit<Name extends keyof Events & (string | symbol)>(eventName: Name, ...args: Events[Name]): boolean {
    return super.emit(eventName, ...args);
  }

  on<Name extends keyof Events & (string | symbol)>(
    eventName: Name,
    listener: (...args: Events[Name]) => void,
  ): this {
    return super.on(eventName, listener);
  }

  addListener<Name extends keyof Events & (string | symbol)>(
    eventName: Name,
    listener: (...args: Events[Name]) => void,
  ): this {
    return super.addListener(eventName, listener);
  }

  once<Name extends keyof Events & (string | symbol)>(
    eventName: Name,
    listener: (...args: Events[Name]) => void,
  ): this {
    return super.once(eventName, listener);
  }

  prependListener<Name extends keyof Events & (string | symbol)>(
    eventName: Name,
    listener: (...args: Events[Name]) => void,
  ): this {
    return super.prependListener(eventName, listener);
  }

  prependOnceListener<Name extends keyof Events & (string | symbol)>(
    eventName: Name,
    listener: (...args: Events[Name]) => void,
  ): this {
    return super.prependOnceListener(eventName, listener);
  }

  off<Name extends keyof Events & (string | symbol)>(
    eventName: Name,
    listener: (...args: Events[Name]) => void,
  ): this {
    return super.off(eventName, listener);
  }

  removeListener<Name extends keyof Events & (string | symbol)>(
    eventName: Name,
    listener: (...args: Events[Name]) => void,
  ): this {
    return super.removeListener(eventName, listener);
  }

  removeAllListeners<Name extends keyof Events & (string | symbol)>(eventName?: Name): this {
    return eventName === undefined
      ? super.removeAllListeners()
      : super.removeAllListeners(eventName);
  }

  listenerCount<Name extends keyof Events & (string | symbol)>(
    eventName: Name,
    listener?: (...args: Events[Name]) => void,
  ): number {
    return super.listenerCount(eventName, listener);
  }

  listeners<Name extends keyof Events & (string | symbol)>(
    eventName: Name,
  ): Array<(...args: Events[Name]) => void> {
    return super.listeners(eventName) as Array<(...args: Events[Name]) => void>;
  }

  rawListeners<Name extends keyof Events & (string | symbol)>(
    eventName: Name,
  ): Array<(...args: Events[Name]) => void> {
    return super.rawListeners(eventName) as Array<(...args: Events[Name]) => void>;
  }
}
