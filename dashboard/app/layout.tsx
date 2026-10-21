import type { Metadata } from 'next';
import localFont from 'next/font/local';
import { AuthProvider } from '@/lib/auth';
import { HelpProvider } from '@/lib/help/HelpContext';
import { LocaleProvider } from '@/lib/locale';
import { LOCALE_COOKIE_NAME, localeOrDefault } from '@/lib/locales';
import { ThemeProvider } from '@/lib/theme';
import { cookies } from 'next/headers';
import './globals.css';

const dmSans = localFont({
  src: './fonts/dm-sans-latin.woff2',
  weight: '100 1000',
  variable: '--font-body',
  display: 'swap',
});

const plusJakarta = localFont({
  src: './fonts/plus-jakarta-sans-latin.woff2',
  weight: '200 800',
  variable: '--font-display',
  display: 'swap',
});

const jetbrainsMono = localFont({
  src: './fonts/jetbrains-mono-latin.woff2',
  weight: '100 800',
  variable: '--font-mono',
  display: 'swap',
  preload: false,
});

const spaceGrotesk = localFont({
  src: './fonts/space-grotesk-latin.woff2',
  weight: '300 700',
  variable: '--font-grotesk',
  display: 'swap',
  preload: false,
});

export const metadata: Metadata = {
  title: 'WrzDJ Dashboard',
  description: 'DJ song request management',
};

export const viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover' as const,
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const cookieStore = await cookies();
  const savedLocale = cookieStore.get(LOCALE_COOKIE_NAME)?.value ?? null;
  const initialLocale = localeOrDefault(savedLocale);

  return (
    <html lang="en" className={`${dmSans.variable} ${plusJakarta.variable} ${jetbrainsMono.variable} ${spaceGrotesk.variable}`}>
      <body>
        <ThemeProvider>
          <LocaleProvider initialLocale={initialLocale}>
            <AuthProvider>
              <HelpProvider>{children}</HelpProvider>
            </AuthProvider>
          </LocaleProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
