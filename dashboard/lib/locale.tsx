'use client';

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { LOCALE_COOKIE_NAME, LOCALE_MESSAGES, type Locale } from './locales';

interface LocaleContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  messages: (typeof LOCALE_MESSAGES)[Locale];
}

const defaultValue: LocaleContextValue = {
  locale: 'en',
  setLocale: () => undefined,
  messages: LOCALE_MESSAGES.en,
};

const LocaleContext = createContext<LocaleContextValue>(defaultValue);

export function LocaleProvider({
  children,
  initialLocale = 'en',
}: {
  children: ReactNode;
  initialLocale?: Locale;
}) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);

  const setLocale = useCallback((nextLocale: Locale) => {
    setLocaleState(nextLocale);
    try {
      const secure = window.location.protocol === 'https:' ? '; Secure' : '';
      document.cookie = `${LOCALE_COOKIE_NAME}=${nextLocale}; Path=/; Max-Age=31536000; SameSite=Lax${secure}`;
    } catch {
      // The in-memory preference still applies when cookies are unavailable.
    }
  }, []);

  const value = useMemo(() => ({ locale, setLocale, messages: LOCALE_MESSAGES[locale] }), [locale, setLocale]);

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleContextValue {
  return useContext(LocaleContext);
}
