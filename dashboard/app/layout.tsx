import type { Metadata } from 'next';
import { DM_Sans, Plus_Jakarta_Sans, JetBrains_Mono, Space_Grotesk } from 'next/font/google';
import { AuthProvider } from '@/lib/auth';
import { HelpProvider } from '@/lib/help/HelpContext';
import { LocaleProvider } from '@/lib/locale';
import { LOCALE_COOKIE_NAME, localeOrDefault } from '@/lib/locales';
import { ThemeProvider } from '@/lib/theme';
import { cookies } from 'next/headers';
import './globals.css';

const dmSans = DM_Sans({
  subsets: ['latin'],
  variable: '--font-body',
  display: 'swap',
});

const plusJakarta = Plus_Jakarta_Sans({
  subsets: ['latin'],
  variable: '--font-display',
  display: 'swap',
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
  preload: false,
});

const spaceGrotesk = Space_Grotesk({
  subsets: ['latin'],
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
