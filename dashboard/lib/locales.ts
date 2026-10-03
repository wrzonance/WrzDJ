export const LOCALES = ['en', 'es'] as const;
export const LOCALE_COOKIE_NAME = 'wrzdj-locale';

export type Locale = (typeof LOCALES)[number];

export interface LocaleMessages {
  dashboard: {
    title: string;
    createEvent: string;
    setBuilder: string;
    bridgeApp: string;
    account: string;
    logout: string;
  };
  language: {
    heading: string;
    label: string;
    english: string;
    spanish: string;
  };
}

export const LOCALE_MESSAGES: Record<Locale, LocaleMessages> = {
  en: {
    dashboard: {
      title: 'Dashboard',
      createEvent: 'Create Event',
      setBuilder: 'Set Builder',
      bridgeApp: 'Bridge App',
      account: 'Account',
      logout: 'Logout',
    },
    language: {
      heading: 'Language',
      label: 'Dashboard language',
      english: 'English',
      spanish: 'Spanish',
    },
  },
  es: {
    dashboard: {
      title: 'Panel',
      createEvent: 'Crear evento',
      setBuilder: 'Creador de sets',
      bridgeApp: 'Aplicación Bridge',
      account: 'Cuenta',
      logout: 'Cerrar sesión',
    },
    language: {
      heading: 'Idioma',
      label: 'Idioma del panel',
      english: 'Inglés',
      spanish: 'Español',
    },
  },
};

export function isLocale(value: string | null): value is Locale {
  return value !== null && LOCALES.includes(value as Locale);
}

export function localeOrDefault(value: string | null): Locale {
  return isLocale(value) ? value : 'en';
}
