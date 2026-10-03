import { act, render, screen } from '@testing-library/react';
import { renderToString } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { LocaleProvider, useLocale } from '../locale';

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
  it('loads a saved locale and reflects it in text, storage, and the document', async () => {
    localStorage.setItem('wrzdj-locale', 'es');
    expect(renderToString(<LocaleProvider><LocaleProbe /></LocaleProvider>)).toContain('Create Event');
    render(<LocaleProvider><LocaleProbe /></LocaleProvider>);

    expect(screen.getByTestId('locale')).toHaveTextContent('es');
    expect(screen.getByText('Crear evento')).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('es');

    localStorage.removeItem('wrzdj-locale');
  });

  it('falls back to English for an unsupported saved locale', async () => {
    localStorage.setItem('wrzdj-locale', 'fr');
    render(<LocaleProvider><LocaleProbe /></LocaleProvider>);

    expect(screen.getByTestId('locale')).toHaveTextContent('en');
    expect(document.documentElement.lang).toBe('en');
    localStorage.removeItem('wrzdj-locale');
  });

  it('persists a user locale selection and updates translated messages', async () => {
    render(<LocaleProvider><LocaleProbe /></LocaleProvider>);

    await act(async () => {
      screen.getByRole('button', { name: 'Choose Spanish' }).click();
    });

    expect(screen.getByText('Crear evento')).toBeInTheDocument();
    expect(localStorage.getItem('wrzdj-locale')).toBe('es');
    expect(document.documentElement.lang).toBe('es');
    localStorage.removeItem('wrzdj-locale');
  });
});
