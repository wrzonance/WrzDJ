'use client';

/**
 * Theme provider for WrzDJ dashboard.
 * Supports three themes: dark (default), high-contrast, daylight.
 * Persists choice to localStorage and sets data-theme attribute on <html>.
 * Auto-detects prefers-contrast: more on first load when no saved preference.
 */

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { THEMES, getThemeVars, type Theme } from './theme-vars';

export type { Theme };

const STORAGE_KEY = 'wrzdj-theme';

interface ThemeContextType {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextType | null>(null);

function isValidTheme(value: string | null): value is Theme {
  return value !== null && (THEMES as readonly string[]).includes(value);
}

function detectInitialTheme(): Theme {
  // 1. Check localStorage
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (isValidTheme(saved)) return saved;
  } catch {
    // localStorage unavailable (SSR, privacy mode)
  }

  // 2. Auto-detect prefers-contrast
  if (typeof window !== 'undefined' && window.matchMedia('(prefers-contrast: more)').matches) {
    return 'high-contrast';
  }

  return 'dark';
}

function applyTheme(theme: Theme): void {
  // Set data-theme attribute
  document.documentElement.setAttribute('data-theme', theme);

  // Apply CSS variables
  const vars = getThemeVars(theme);
  for (const [key, value] of Object.entries(vars)) {
    document.documentElement.style.setProperty(key, value);
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Start from a deterministic default so the server-rendered markup matches
  // the client's first (hydration) render. Reading localStorage during render
  // would diverge server (no storage → 'dark') from client (saved → e.g.
  // 'daylight') and trip React's hydration-mismatch warning. The persisted /
  // auto-detected theme is loaded just below, after mount.
  const [theme, setThemeState] = useState<Theme>('dark');

  // Resolve the real theme on the client, post-hydration.
  useEffect(() => {
    const initial = detectInitialTheme();
    if (initial !== 'dark') setThemeState(initial);
  }, []);

  const setTheme = useCallback((newTheme: Theme) => {
    setThemeState(newTheme);
    try {
      localStorage.setItem(STORAGE_KEY, newTheme);
    } catch {
      // localStorage unavailable
    }
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((current) => {
      const currentIndex = THEMES.indexOf(current);
      const next = THEMES[(currentIndex + 1) % THEMES.length];
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        // localStorage unavailable
      }
      return next;
    });
  }, []);

  // Apply theme to DOM whenever it changes
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextType {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return ctx;
}
