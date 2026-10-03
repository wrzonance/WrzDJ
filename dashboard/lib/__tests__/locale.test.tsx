import { act, render, screen } from '@testing-library/react';
import { renderToString } from 'react-dom/server';
import { beforeEach, describe, expect, it } from 'vitest';
import { LocaleProvider, useLocale } from '../locale';
import { localeOrDefault } from '../locales';

function LocaleProbe() {
  const { locale, setLocale, messages } = useLocale();
  return (
    <div>
      <span data-testid="locale">{locale}</span>
      <span>{messages.dashboard.createEvent}</span>
      <button onClick={() => setLocale('es')}>Choose Spanish</button>
    </div>
  );
}

describe('LocaleProvider', () => {
  beforeEach(() => {
    document.documentElement.lang = 'en';
    document.cookie = 'wrzdj-locale=; Path=/; Max-Age=0';
  });

  it('renders a saved locale immediately on the server and client', () => {
    expect(renderToString(<LocaleProvider initialLocale="es"><LocaleProbe /></LocaleProvider>)).toContain('Crear evento');
    render(<LocaleProvider initialLocale="es"><LocaleProbe /></LocaleProvider>);

    expect(screen.getByTestId('locale')).toHaveTextContent('es');
    expect(screen.getByText('Crear evento')).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('en');
  });

  it('falls back to English for an unsupported saved locale', async () => {
    expect(localeOrDefault('fr')).toBe('en');
    render(<LocaleProvider initialLocale={localeOrDefault('fr')}><LocaleProbe /></LocaleProvider>);

    expect(screen.getByTestId('locale')).toHaveTextContent('en');
    expect(document.documentElement.lang).toBe('en');
  });

  it('persists a user locale selection and updates translated messages', async () => {
    render(<LocaleProvider><LocaleProbe /></LocaleProvider>);

    await act(async () => {
      screen.getByRole('button', { name: 'Choose Spanish' }).click();
    });

    expect(screen.getByText('Crear evento')).toBeInTheDocument();
    expect(document.cookie).toContain('wrzdj-locale=es');
    expect(document.documentElement.lang).toBe('en');
  });
});
