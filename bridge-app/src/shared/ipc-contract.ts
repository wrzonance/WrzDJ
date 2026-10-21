import type { IpcMainInvokeEvent } from 'electron';
import { IPC_CHANNELS } from './types.js';
import type {
  AuthState,
  BridgeSettings,
  BridgeStatus,
  EventInfo,
  IpcLogMessage,
  PluginMeta,
} from './types.js';

type InvokeHandler<Args extends unknown[], Result> = (
  event: IpcMainInvokeEvent,
  ...args: Args
) => Result | Promise<Result>;

/** Argument and result types for every renderer-invokable main-process channel. */
export interface IpcHandlerMap {
  [IPC_CHANNELS.AUTH_LOGIN]: InvokeHandler<[apiUrl: string, username: string, password: string], void>;
  [IPC_CHANNELS.AUTH_LOGOUT]: InvokeHandler<[], void>;
  [IPC_CHANNELS.AUTH_GET_STATE]: InvokeHandler<[], AuthState>;
  [IPC_CHANNELS.PLUGINS_LIST_META]: InvokeHandler<[], readonly PluginMeta[]>;
  [IPC_CHANNELS.EVENTS_FETCH]: InvokeHandler<[], readonly EventInfo[]>;
  [IPC_CHANNELS.BRIDGE_START]: InvokeHandler<[eventCode: string], void>;
  [IPC_CHANNELS.BRIDGE_STOP]: InvokeHandler<[], void>;
  [IPC_CHANNELS.BRIDGE_RESET_DECKS]: InvokeHandler<[], void>;
  [IPC_CHANNELS.BRIDGE_RECONNECT]: InvokeHandler<[], void>;
  [IPC_CHANNELS.BRIDGE_RESTART]: InvokeHandler<[], void>;
  [IPC_CHANNELS.SETTINGS_GET]: InvokeHandler<[], BridgeSettings>;
  [IPC_CHANNELS.SETTINGS_UPDATE]: InvokeHandler<[partial: Partial<BridgeSettings>], BridgeSettings>;
  [IPC_CHANNELS.BRIDGE_EXPORT_DEBUG_REPORT]: InvokeHandler<[], string | null>;
}

/** Main-process event channels and their exact renderer payload tuples. */
export interface RendererEventMap {
  [IPC_CHANNELS.AUTH_CHANGED]: [state: AuthState];
  [IPC_CHANNELS.BRIDGE_STATUS]: [status: BridgeStatus];
  [IPC_CHANNELS.BRIDGE_LOG]: [message: IpcLogMessage];
  [IPC_CHANNELS.BRIDGE_PING]: [];
}
