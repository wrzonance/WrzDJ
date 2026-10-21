import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { EventCustomizationCard } from '../EventCustomizationCard';
import type { Event } from '@/lib/api/types';

const event = (banner_url: string | null): Event => ({
  banner_url,
} as Event);

describe('EventCustomizationCard', () => {
  it('offers image upload with supported formats and reports selected files', () => {
    const onBannerSelect = vi.fn();
    render(
      <EventCustomizationCard
        event={event(null)}
        uploadingBanner={false}
        onBannerSelect={onBannerSelect}
        onDeleteBanner={vi.fn()}
      />,
    );

    expect(screen.getByText('Upload')).toBeInTheDocument();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input.accept).toBe('image/jpeg,image/png,image/gif,image/webp');
    fireEvent.change(input, { target: { files: [new File(['banner'], 'banner.webp', { type: 'image/webp' })] } });
    expect(onBannerSelect).toHaveBeenCalledOnce();
  });

  it('prevents replacement/removal during upload and removes an existing banner on request', () => {
    const onDeleteBanner = vi.fn();
    const { rerender } = render(
      <EventCustomizationCard
        event={event('https://example.test/banner.webp')}
        uploadingBanner
        onBannerSelect={vi.fn()}
        onDeleteBanner={onDeleteBanner}
      />,
    );
    expect(screen.getByText('Uploading...')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Remove' })).toBeDisabled();

    rerender(
      <EventCustomizationCard
        event={event('https://example.test/banner.webp')}
        uploadingBanner={false}
        onBannerSelect={vi.fn()}
        onDeleteBanner={onDeleteBanner}
      />,
    );
    expect(screen.getByAltText('Event banner')).toHaveAttribute('src', 'https://example.test/banner.webp');
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    expect(onDeleteBanner).toHaveBeenCalledOnce();
  });
});
