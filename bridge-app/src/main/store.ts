import Store from 'electron-store';
import { safeStorage } from 'electron';
import { DEFAULT_SETTINGS, type BridgeSettings } from '../shared/types.js';

interface StoreSchema {
  apiUrl: string;
  encryptedToken: string;
  lastEventCode: string;
  settings: BridgeSettings;
}

let store: Store<StoreSchema> | null = null;

export function initializeStore(): void {
  store ??= new Store<StoreSchema>({
    defaults: {
      apiUrl: 'https://api.wrzdj.com',
      encryptedToken: '',
      lastEventCode: '',
      settings: DEFAULT_SETTINGS,
    },
  });
}

function getStore(): Store<StoreSchema> {
  if (!store) throw new Error('Persistent store has not been initialized');
  return store;
}

// In-memory fallback when OS keychain encryption is unavailable.
// Token is lost on app restart — user must re-authenticate.
let sessionToken: string | null = null;

function useMemoryTokenFallback(token: string, warning: string): void {
  console.warn(warning);
  try {
    getStore().set('encryptedToken', '');
  } catch {
    console.warn('[Store] Could not clear persisted token for memory fallback');
  }
  sessionToken = token;
}

export function getApiUrl(): string {
  return getStore().get('apiUrl');
}

export function setApiUrl(url: string): void {
  getStore().set('apiUrl', url);
}

export function readAndRepairToken(): string | null {
  if (sessionToken !== null) return sessionToken;

  const encrypted = getStore().get('encryptedToken');

  if (!safeStorage.isEncryptionAvailable()) {
    return null;
  }

  if (!encrypted) return null;

  try {
    const buffer = Buffer.from(encrypted, 'base64');
    return safeStorage.decryptString(buffer);
  } catch {
    getStore().set('encryptedToken', '');
    return null;
  }
}

export function setToken(token: string): void {
  if (!safeStorage.isEncryptionAvailable()) {
    useMemoryTokenFallback(token, '[Store] OS keychain encryption unavailable — token stored in memory only');
    return;
  }

  try {
    const encrypted = safeStorage.encryptString(token);
    getStore().set('encryptedToken', encrypted.toString('base64'));
    sessionToken = null;
  } catch {
    useMemoryTokenFallback(token, '[Store] Token encryption failed — storing in memory only');
  }
}

export function clearToken(): void {
  getStore().set('encryptedToken', '');
  sessionToken = null;
}

export function getLastEventCode(): string {
  return getStore().get('lastEventCode');
}

export function setLastEventCode(code: string): void {
  getStore().set('lastEventCode', code);
}

export function getSettings(): BridgeSettings {
  return getStore().get('settings');
}

export function updateSettings(partial: Partial<BridgeSettings>): BridgeSettings {
  const current = getSettings();
  const updated = { ...current, ...partial };
  getStore().set('settings', updated);
  return updated;
}
