import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  construct: vi.fn(),
  get: vi.fn(),
  set: vi.fn(),
  isEncryptionAvailable: vi.fn(),
  encryptString: vi.fn(),
  decryptString: vi.fn(),
}));

vi.mock('electron-store', () => ({
  default: class MockStore {
    constructor() { mocks.construct(); }
    get = mocks.get;
    set = mocks.set;
  },
}));

vi.mock('electron', () => ({
  safeStorage: {
    isEncryptionAvailable: mocks.isEncryptionAvailable,
    encryptString: mocks.encryptString,
    decryptString: mocks.decryptString,
  },
}));

const importStore = async () => import('../store.js');

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
  mocks.set.mockImplementation(() => undefined);
  mocks.get.mockImplementation((key: string) => key === 'encryptedToken' ? '' : undefined);
  mocks.isEncryptionAvailable.mockReturnValue(true);
  mocks.encryptString.mockReturnValue(Buffer.from('encrypted-token'));
  mocks.decryptString.mockReturnValue('decrypted-token');
});

describe('token storage', () => {
  it('warns about in-memory token fallback without logging the token', async () => {
    const store = await importStore();
    store.initializeStore();
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mocks.isEncryptionAvailable.mockReturnValue(false);
    mocks.get.mockImplementation((key: string) => key === 'encryptedToken' ? 'stale-value' : undefined);

    store.setToken('credential-must-stay-private');

    expect(warn).toHaveBeenCalledOnce();
    expect(warn.mock.calls.flat().join(' ')).not.toContain('credential-must-stay-private');
    expect(mocks.set).toHaveBeenCalledWith('encryptedToken', '');
    expect(store.readAndRepairToken()).toBe('credential-must-stay-private');
    warn.mockRestore();
  });

  it('returns the in-memory token when encryption fails despite keychain availability', async () => {
    const store = await importStore();
    store.initializeStore();
    mocks.get.mockImplementation((key: string) => key === 'encryptedToken' ? 'stale-value' : undefined);
    mocks.encryptString.mockImplementation(() => { throw new Error('keychain error'); });
    store.setToken('session-token');

    expect(mocks.set).toHaveBeenCalledWith('encryptedToken', '');
    expect(store.readAndRepairToken()).toBe('session-token');
  });

  it('keeps the new in-memory token when stale credential cleanup fails', async () => {
    const store = await importStore();
    store.initializeStore();
    mocks.get.mockImplementation((key: string) => key === 'encryptedToken' ? 'stale-value' : undefined);
    mocks.encryptString.mockImplementation(() => { throw new Error('keychain error'); });
    mocks.set.mockImplementation(() => { throw new Error('store unavailable'); });

    expect(() => store.setToken('session-token')).not.toThrow();
    expect(mocks.set).toHaveBeenCalledWith('encryptedToken', '');
    expect(store.readAndRepairToken()).toBe('session-token');
  });

  it('repairs unreadable encrypted token storage through the explicitly named reader', async () => {
    const store = await importStore();
    store.initializeStore();
    mocks.get.mockImplementation((key: string) => key === 'encryptedToken' ? 'invalid-base64-payload' : undefined);
    mocks.decryptString.mockImplementation(() => { throw new Error('decrypt failed'); });

    expect(store.readAndRepairToken()).toBeNull();
    expect(mocks.set).toHaveBeenCalledWith('encryptedToken', '');
  });

  it('constructs persistent storage only after explicit initialization', async () => {
    const store = await importStore();

    expect(mocks.construct).not.toHaveBeenCalled();
    store.initializeStore();
    store.initializeStore();
    expect(mocks.construct).toHaveBeenCalledOnce();
  });
});
