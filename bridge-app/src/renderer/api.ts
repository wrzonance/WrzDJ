import type { BridgeApi } from '../shared/bridge-api.js';

declare global {
  interface Window {
    bridgeApi: BridgeApi;
  }
}

export const api: BridgeApi = window.bridgeApi;
