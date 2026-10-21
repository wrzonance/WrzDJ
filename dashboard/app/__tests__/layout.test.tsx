import type { ReactNode } from 'react';
import { isValidElement, type ReactElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import RootLayout, { metadata, viewport } from '../layout';

const mocks = vi.hoisted(() => ({ locale: 'es' as string | undefined }));

vi.mock('next/font/local', () => ({
  default: ({ variable }: { variable: string }) => ({ variable }),
}));
vi.mock('next/headers', () => ({
  cookies: async () => ({ get: () => mocks.locale ? { value: mocks.locale } : undefined }),
}));
vi.mock('@/lib/theme', () => ({ ThemeProvider: ({ children }: { children: ReactNode }) => <div>{children}</div> }));
vi.mock('@/lib/locale', () => ({
  LocaleProvider: ({ initialLocale, children }: { initialLocale: string; children: ReactNode }) => (
    <div data-initial-locale={initialLocale}>{children}</div>
  ),
}));
vi.mock('@/lib/auth', () => ({ AuthProvider: ({ children }: { children: ReactNode }) => <div>{children}</div> }));
vi.mock('@/lib/help/HelpContext', () => ({ HelpProvider: ({ children }: { children: ReactNode }) => <div>{children}</div> }));

describe('root layout', () => {
  beforeEach(() => { mocks.locale = 'es'; });

  it('initializes the locale from the saved cookie and keeps document metadata', async () => {
    const tree = await RootLayout({ children: <span>page</span> });
    expect(isValidElement(tree)).toBe(true);
    if (!isValidElement(tree)) throw new Error('Root layout must return the html document');

    const html = tree as ReactElement<{ lang: string; children: ReactElement }>;
    const body = html.props.children as ReactElement<{ children: ReactElement }>;
    const themeProvider = body.props.children as ReactElement<{ children: ReactElement }>;
    const localeProvider = themeProvider.props.children as ReactElement<{ initialLocale: string }>;

    expect(html.props.lang).toBe('en');
    expect(localeProvider.props.initialLocale).toBe('es');
    expect(metadata.title).toBe('WrzDJ Dashboard');
    expect(viewport.viewportFit).toBe('cover');
  });

  it('uses the default locale when the cookie contains an unsupported value', async () => {
    mocks.locale = 'unsupported';
    const tree = await RootLayout({ children: <span>page</span> });
    if (!isValidElement(tree)) throw new Error('Root layout must return the html document');

    const html = tree as ReactElement<{ children: ReactElement }>;
    const body = html.props.children as ReactElement<{ children: ReactElement }>;
    const themeProvider = body.props.children as ReactElement<{ children: ReactElement }>;
    const localeProvider = themeProvider.props.children as ReactElement<{ initialLocale: string }>;
    expect(localeProvider.props.initialLocale).toBe('en');
  });
});
