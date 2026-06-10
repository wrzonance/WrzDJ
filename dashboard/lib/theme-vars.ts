/**
 * CSS variable maps for each theme.
 *
 * Tier 1 — surfaces & structure (9 vars)
 * Tier 2 — semantic action colors (14 vars)
 * Tier 3 — named UI roles (15 vars)
 *
 * dark:          Default. Pure dark, standard contrast.
 * high-contrast: Boosted contrast for accessibility / bright environments.
 * daylight:      True light mode — white background, dark text.
 */

export type Theme = 'dark' | 'high-contrast' | 'daylight';

export const THEMES: readonly Theme[] = ['dark', 'high-contrast', 'daylight'] as const;

const THEME_VARS: Record<Theme, Record<string, string>> = {
  dark: {
    // Tier 1 — surfaces & structure
    '--bg':             '#0a0a0a',
    '--card':           '#1a1a1a',
    '--surface-raised': '#111111',
    '--text':           '#ededed',
    '--text-secondary': '#9ca3af',
    '--text-tertiary':  '#6b7280',
    '--border':         '#333333',
    '--border-subtle':  '#222222',
    '--color-overlay':  'rgba(0,0,0,0.7)',

    // Tier 2 — semantic actions
    '--color-primary':        '#3b82f6',
    '--color-primary-hover':  '#2563eb',
    '--color-primary-subtle': 'rgba(59,130,246,0.12)',
    '--color-danger':         '#ef4444',
    '--color-danger-hover':   '#dc2626',
    '--color-danger-subtle':  'rgba(239,68,68,0.12)',
    '--color-success':        '#22c55e',
    '--color-success-hover':  '#16a34a',
    '--color-success-subtle': 'rgba(34,197,94,0.12)',
    '--color-warning':        '#f59e0b',
    '--color-warning-hover':  '#d97706',
    '--color-warning-subtle': 'rgba(245,158,11,0.12)',
    '--color-admin':          '#6b21a8',
    '--color-admin-subtle':   'rgba(107,33,168,0.15)',

    // Tier 3 — named UI roles
    '--color-link':             '#60a5fa',
    '--color-nickname-accent':  '#a78bfa',
    '--color-code-accent':      '#3b82f6',
    '--color-focus-ring':       'rgba(59,130,246,0.4)',
    '--color-scrollbar':        '#444444',
    '--color-log-info-bg':      '#1e3a5f',
    '--color-log-info-text':    '#60a5fa',
    '--color-log-warning-bg':   '#78350f',
    '--color-log-warning-text': '#fbbf24',
    '--color-log-error-bg':     '#7f1d1d',
    '--color-log-error-text':   '#f87171',
    '--color-accent-checkbox':  '#3b82f6',
    '--color-live-badge':       '#ef4444',
    '--color-status-accepted':  '#8b5cf6',
    '--color-curve-accent':     '#00f5d4',
  },

  'high-contrast': {
    // Tier 1
    '--bg':             '#000000',
    '--card':           '#111111',
    '--surface-raised': '#0a0a0a',
    '--text':           '#ffffff',
    '--text-secondary': '#d1d5db',
    '--text-tertiary':  '#9ca3af',
    '--border':         '#555555',
    '--border-subtle':  '#333333',
    '--color-overlay':  'rgba(0,0,0,0.85)',

    // Tier 2
    '--color-primary':        '#60a5fa',
    '--color-primary-hover':  '#3b82f6',
    '--color-primary-subtle': 'rgba(59,130,246,0.2)',
    '--color-danger':         '#f87171',
    '--color-danger-hover':   '#ef4444',
    '--color-danger-subtle':  'rgba(239,68,68,0.2)',
    '--color-success':        '#4ade80',
    '--color-success-hover':  '#22c55e',
    '--color-success-subtle': 'rgba(34,197,94,0.2)',
    '--color-warning':        '#fbbf24',
    '--color-warning-hover':  '#f59e0b',
    '--color-warning-subtle': 'rgba(245,158,11,0.2)',
    '--color-admin':          '#7c3aed',
    '--color-admin-subtle':   'rgba(124,58,237,0.2)',

    // Tier 3
    '--color-link':             '#93c5fd',
    '--color-nickname-accent':  '#c4b5fd',
    '--color-code-accent':      '#60a5fa',
    '--color-focus-ring':       'rgba(59,130,246,0.6)',
    '--color-scrollbar':        '#666666',
    '--color-log-info-bg':      '#1e3a5f',
    '--color-log-info-text':    '#93c5fd',
    '--color-log-warning-bg':   '#92400e',
    '--color-log-warning-text': '#fde68a',
    '--color-log-error-bg':     '#991b1b',
    '--color-log-error-text':   '#fca5a5',
    '--color-accent-checkbox':  '#60a5fa',
    '--color-live-badge':       '#f87171',
    '--color-status-accepted':  '#a78bfa',
    '--color-curve-accent':     '#00f5d4',
  },

  daylight: {
    // Tier 1
    '--bg':             '#f8fafc',
    '--card':           '#ffffff',
    '--surface-raised': '#f1f5f9',
    '--text':           '#0f172a',
    '--text-secondary': '#475569',
    '--text-tertiary':  '#64748b',
    '--border':         '#e2e8f0',
    '--border-subtle':  '#f1f5f9',
    '--color-overlay':  'rgba(0,0,0,0.5)',

    // Tier 2
    '--color-primary':        '#2563eb',
    '--color-primary-hover':  '#1d4ed8',
    '--color-primary-subtle': 'rgba(37,99,235,0.1)',
    '--color-danger':         '#dc2626',
    '--color-danger-hover':   '#b91c1c',
    '--color-danger-subtle':  'rgba(220,38,38,0.1)',
    '--color-success':        '#16a34a',
    '--color-success-hover':  '#15803d',
    '--color-success-subtle': 'rgba(22,163,74,0.1)',
    '--color-warning':        '#d97706',
    '--color-warning-hover':  '#b45309',
    '--color-warning-subtle': 'rgba(245,158,11,0.1)',
    '--color-admin':          '#7c3aed',
    '--color-admin-subtle':   'rgba(124,58,237,0.1)',

    // Tier 3
    '--color-link':             '#2563eb',
    '--color-nickname-accent':  '#7c3aed',
    '--color-code-accent':      '#2563eb',
    '--color-focus-ring':       'rgba(37,99,235,0.3)',
    '--color-scrollbar':        '#cbd5e1',
    '--color-log-info-bg':      '#dbeafe',
    '--color-log-info-text':    '#1d4ed8',
    '--color-log-warning-bg':   '#fef3c7',
    '--color-log-warning-text': '#92400e',
    '--color-log-error-bg':     '#fee2e2',
    '--color-log-error-text':   '#991b1b',
    '--color-accent-checkbox':  '#2563eb',
    '--color-live-badge':       '#dc2626',
    '--color-status-accepted':  '#7c3aed',
    '--color-curve-accent':     '#0f766e',
  },
};

export function getThemeVars(theme: Theme): Record<string, string> {
  return { ...THEME_VARS[theme] };
}
