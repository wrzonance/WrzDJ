'use client';

import { useTheme, type Theme } from '@/lib/theme';
import { useHelp } from '@/lib/help/HelpContext';

const THEME_LABELS: Record<Theme, string> = {
  dark: 'Dark',
  'high-contrast': 'Hi-Con',
  daylight: 'Day',
};

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const { onboardingActive } = useHelp();

  if (onboardingActive) return null;

  return (
    <button
      onClick={toggleTheme}
      className="theme-toggle"
      title={`Theme: ${THEME_LABELS[theme]} (click to change)`}
      aria-label={`Current theme: ${THEME_LABELS[theme]}. Click to change.`}
    >
      <span className={`theme-toggle-icon theme-toggle-icon--${theme}`} />
      <span className="theme-toggle-label">{THEME_LABELS[theme]}</span>
    </button>
  );
}
