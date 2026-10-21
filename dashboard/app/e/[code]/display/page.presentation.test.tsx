import { act, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { mockKioskDisplay, mockNowPlaying, setupDefaultMocks } from './pageTestSupport';
import KioskDisplayPage from './page';
import { api } from '@/lib/api';

describe('KioskDisplayPage', () => {


  describe('Kiosk protections', () => {
    it('prevents context menu', async () => {
      setupDefaultMocks();

      render(<KioskDisplayPage />);
      await screen.findByText('Test Event');

      const event = new Event('contextmenu', { cancelable: true });
      const prevented = !document.dispatchEvent(event);
      expect(prevented).toBe(true);
    });

    it('prevents text selection', async () => {
      setupDefaultMocks();

      render(<KioskDisplayPage />);
      await screen.findByText('Test Event');

      const event = new Event('selectstart', { cancelable: true });
      const prevented = !document.dispatchEvent(event);
      expect(prevented).toBe(true);
    });

    it('prevents drag and removes browser guards after unmount', async () => {
      setupDefaultMocks();

      const { unmount } = render(<KioskDisplayPage />);
      await screen.findByText('Test Event');

      const drag = new Event('dragstart', { cancelable: true });
      expect(document.dispatchEvent(drag)).toBe(false);

      unmount();

      const contextMenu = new Event('contextmenu', { cancelable: true });
      const dragAfterUnmount = new Event('dragstart', { cancelable: true });
      expect(document.dispatchEvent(contextMenu)).toBe(true);
      expect(document.dispatchEvent(dragAfterUnmount)).toBe(true);
    });
  });

  describe('Display-only queue scrolling', () => {
    it('scrolls by 85px, returns to top near the bottom, and stops after unmount', async () => {
      vi.useFakeTimers();
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        kiosk_display_only: true,
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      const { unmount } = render(<KioskDisplayPage />);
      await act(async () => { await vi.advanceTimersByTimeAsync(100); });

      const queueList = document.querySelector('.queue-list') as HTMLElement;
      const scrollBy = vi.fn();
      const scrollTo = vi.fn();
      queueList.scrollBy = scrollBy;
      queueList.scrollTo = scrollTo;
      Object.defineProperty(queueList, 'clientHeight', { configurable: true, value: 100 });
      Object.defineProperty(queueList, 'scrollHeight', { configurable: true, value: 500 });

      await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
      expect(scrollBy).toHaveBeenCalledWith({ top: 85, behavior: 'smooth' });

      Object.defineProperty(queueList, 'scrollTop', { configurable: true, value: 400 });
      await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
      expect(scrollTo).toHaveBeenCalledWith({ top: 0, behavior: 'smooth' });

      unmount();
      await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
      expect(scrollBy).toHaveBeenCalledTimes(1);
      expect(scrollTo).toHaveBeenCalledTimes(1);
    });
  });

  describe('Banner', () => {
    it('applies banner gradient with valid colors', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        banner_colors: ['#1a2b3c', '#4d5e6f', '#7a8b9c'],
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      const container = screen.getByText('Test Event').closest('.kiosk-container') as HTMLElement;
      const bgStyle = container?.style.getPropertyValue('--kiosk-bg');
      expect(bgStyle).toContain('#1a2b3c');
      expect(bgStyle).toContain('#4d5e6f');
      expect(bgStyle).toContain('#7a8b9c');
    });

    it('falls back for invalid color values', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        banner_colors: ['bad', '#4d5e6f', 'nope'],
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      const container = screen.getByText('Test Event').closest('.kiosk-container') as HTMLElement;
      const bgStyle = container?.style.getPropertyValue('--kiosk-bg');
      // Should use fallback for invalid colors
      expect(bgStyle).toContain('#1a1a2e'); // fallback for first
      expect(bgStyle).toContain('#4d5e6f'); // valid
      expect(bgStyle).toContain('#0f3460'); // fallback for third
    });

    it('renders banner image when present', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        banner_kiosk_url: '/uploads/banners/test-kiosk.webp',
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      const bannerBg = document.querySelector('.kiosk-banner-bg img') as HTMLImageElement;
      expect(bannerBg).toBeInTheDocument();
      expect(bannerBg.src).toContain('/uploads/banners/test-kiosk.webp');
    });

    it('does not render banner when no banner_kiosk_url', async () => {
      setupDefaultMocks();

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      expect(document.querySelector('.kiosk-banner-bg')).not.toBeInTheDocument();
    });

    it('hides banner container on image load error', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue({
        ...mockKioskDisplay,
        banner_kiosk_url: '/uploads/banners/missing-kiosk.webp',
      });
      vi.mocked(api.getNowPlaying).mockResolvedValue(null);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      const bannerImg = document.querySelector('.kiosk-banner-bg img') as HTMLImageElement;
      expect(bannerImg).toBeInTheDocument();

      // Simulate image load error
      await act(async () => {
        bannerImg.dispatchEvent(new Event('error'));
      });

      // Parent container should be hidden
      const bannerBg = document.querySelector('.kiosk-banner-bg') as HTMLElement;
      expect(bannerBg.style.display).toBe('none');
    });
  });

  describe('Kiosk-specific styling', () => {
    it('shows plus icon on request button', async () => {
      setupDefaultMocks();

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      const button = screen.getByRole('button', { name: /request a song/i });
      expect(button.querySelector('svg')).toBeInTheDocument();
    });

    it('applies cursor:none to global styles', async () => {
      setupDefaultMocks();

      render(<KioskDisplayPage />);

      await screen.findByText('Test Event');

      // Check that the global style tag contains cursor: none
      const styleTags = document.querySelectorAll('style');
      const hasNoCursor = Array.from(styleTags).some(
        (tag) => tag.textContent?.includes('cursor: none') || tag.textContent?.includes('cursor:none')
      );
      expect(hasNoCursor).toBe(true);
    });
  });

  describe('Artwork rendering', () => {
    it('shows album art image when URL is present', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue(mockNowPlaying);
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Currently Playing Song');

      const img = screen.getByAltText('Currently Playing Song') as HTMLImageElement;
      expect(img.src).toContain('example.com/art.jpg');
    });

    it('shows placeholder when no album art', async () => {
      vi.mocked(api.getKioskDisplay).mockResolvedValue(mockKioskDisplay);
      vi.mocked(api.getNowPlaying).mockResolvedValue({
        ...mockNowPlaying,
        album_art_url: null,
      });
      vi.mocked(api.getPlayHistory).mockResolvedValue({ items: [], total: 0 });

      render(<KioskDisplayPage />);

      await screen.findByText('Currently Playing Song');

      expect(document.querySelector('.now-playing-placeholder')).toBeInTheDocument();
    });
  });
});
