import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { EventErrorCard } from '../EventErrorCard';

vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
  }) => <a href={href} {...props}>{children}</a>,
}));

describe('EventErrorCard', () => {
  // Regression baseline 57cfcdc6867f: the event page mocks this card, so verify its status copy here.
  it.each([
    [{ message: 'missing', status: 404 }, 'Event Not Found', 'This event does not exist.'],
    [{ message: 'expired', status: 410 }, 'Event Expired', 'This event has expired and is no longer accepting requests.'],
    [{ message: 'Try again later', status: 503 }, 'Error', 'Try again later'],
  ] as const)('shows the appropriate public error for status %s', (error, heading, message) => {
    render(<EventErrorCard error={error} />);

    expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument();
    expect(screen.getByText(message)).toBeInTheDocument();
  });

  it('uses the fallback when no error message exists and links back to the requested destination', () => {
    render(
      <EventErrorCard
        error={null}
        fallbackMessage="The event could not be loaded."
        backLink={{ href: '/events', label: 'Back to events' }}
      />,
    );

    expect(screen.getByText('The event could not be loaded.')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Back to events' });
    expect(link).toHaveAttribute('href', '/events');
  });
});
