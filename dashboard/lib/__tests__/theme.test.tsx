import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import { renderToString } from 'react-dom/server';
import { ThemeProvider, useTheme } from '../theme';
import { getThemeVars } from '../theme-vars';

// Test component that exposes theme context values
function ThemeConsumer() {
  const { theme, setTheme, toggleTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <button data-testid="toggle" onClick={toggleTheme}>Toggle</button>
      <button data-testid="set-daylight" onClick={() => setTheme('daylight')}>Daylight</button>
      <button data-testid="set-hc" onClick={() => setTheme('high-contrast')}>HC</button>
    </div>
  );
}

function renderWithProvider() {
  return render(
    <ThemeProvider>
      <ThemeConsumer />
    </ThemeProvider>
  );
}

// Helper to create a matchMedia mock
function createMatchMedia(contrastMore = false) {
  return (query: string): MediaQueryList => ({
    matches: contrastMore && query === '(prefers-contrast: more)',
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  });
}

// Simple in-memory localStorage replacement for tests
function createMockStorage(): Storage {
  const store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { for (const k of Object.keys(store)) delete store[k]; },
    get length() { return Object.keys(store).length; },
    key: (index: number) => Object.keys(store)[index] ?? null,
    _store: store,
  } as Storage & { _store: Record<string, string> };
}

describe('ThemeProvider', () => {
  const originalMatchMedia = window.matchMedia;
  const originalLocalStorage = window.localStorage;
  let mockStorage: ReturnType<typeof createMockStorage>;

  beforeEach(() => {
    mockStorage = createMockStorage();
    Object.defineProperty(window, 'localStorage', { value: mockStorage, writable: true, configurable: true });

    // Default: no prefers-contrast
    window.matchMedia = createMatchMedia(false);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    window.matchMedia = originalMatchMedia;
    Object.defineProperty(window, 'localStorage', { value: originalLocalStorage, writable: true });
    document.documentElement.removeAttribute('data-theme');
    for (const key of Object.keys(getThemeVars('dark'))) {
      document.documentElement.style.removeProperty(key);
    }
  });

  it('defaults to dark theme when no localStorage and no prefers-contrast', () => {
    renderWithProvider();
    expect(screen.getByTestId('theme').textContent).toBe('dark');
  });

  it('reads saved theme from localStorage', () => {
    localStorage.setItem('wrzdj-theme', 'daylight');
    renderWithProvider();
    expect(screen.getByTestId('theme').textContent).toBe('daylight');
  });

  it('auto-detects prefers-contrast: more on first load', () => {
    window.matchMedia = createMatchMedia(true);
    renderWithProvider();
    expect(screen.getByTestId('theme').textContent).toBe('high-contrast');
  });

  it('prefers localStorage over prefers-contrast detection', () => {
    localStorage.setItem('wrzdj-theme', 'daylight');
    window.matchMedia = createMatchMedia(true);
    renderWithProvider();
    expect(screen.getByTestId('theme').textContent).toBe('daylight');
  });

  it('setTheme updates theme and persists to localStorage', () => {
    renderWithProvider();
    act(() => {
      screen.getByTestId('set-daylight').click();
    });
    expect(screen.getByTestId('theme').textContent).toBe('daylight');
    expect(localStorage.getItem('wrzdj-theme')).toBe('daylight');
  });

  it('toggleTheme cycles dark -> high-contrast -> daylight -> dark', () => {
    renderWithProvider();
    expect(screen.getByTestId('theme').textContent).toBe('dark');

    act(() => { screen.getByTestId('toggle').click(); });
    expect(screen.getByTestId('theme').textContent).toBe('high-contrast');

    act(() => { screen.getByTestId('toggle').click(); });
    expect(screen.getByTestId('theme').textContent).toBe('daylight');

    act(() => { screen.getByTestId('toggle').click(); });
    expect(screen.getByTestId('theme').textContent).toBe('dark');
  });

  it('sets data-theme attribute on documentElement', () => {
    renderWithProvider();
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');

    act(() => { screen.getByTestId('set-hc').click(); });
    expect(document.documentElement.getAttribute('data-theme')).toBe('high-contrast');
  });

  it('ignores invalid saved theme values', () => {
    localStorage.setItem('wrzdj-theme', 'invalid-theme');
    renderWithProvider();
    expect(screen.getByTestId('theme').textContent).toBe('dark');
  });

  it('server-renders the default theme regardless of saved theme (hydration-safe)', () => {
    // The server has no localStorage, so its markup must match the client's
    // FIRST render. If the provider read localStorage during render, the
    // server (dark) and client (daylight) markup would diverge → React
    // hydration mismatch. Saved theme is loaded post-mount instead.
    localStorage.setItem('wrzdj-theme', 'daylight');
    const html = renderToString(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>
    );
    expect(html).toContain('data-testid="theme">dark<');
    expect(html).not.toContain('data-testid="theme">daylight<');
  });
});
