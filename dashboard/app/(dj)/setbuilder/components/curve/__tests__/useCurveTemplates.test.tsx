import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useCurveTemplates } from '../useCurveTemplates';

const mockApi = vi.hoisted(() => ({
  getCurveTemplates: vi.fn(),
  createCurveTemplate: vi.fn(),
  updateCurveTemplate: vi.fn(),
  deleteCurveTemplate: vi.fn(),
}));

vi.mock('@/lib/api', () => ({ api: mockApi }));

const templates = { builtin: [], user: [] };
const savedTemplate = { id: 12, name: 'Saved', points: [] };

beforeEach(() => {
  vi.resetAllMocks();
  mockApi.getCurveTemplates.mockResolvedValue(templates);
  mockApi.createCurveTemplate.mockResolvedValue(savedTemplate);
  mockApi.updateCurveTemplate.mockResolvedValue(savedTemplate);
  mockApi.deleteCurveTemplate.mockResolvedValue(undefined);
});

describe('useCurveTemplates', () => {
  it('loads templates and refreshes after create, update, and delete', async () => {
    const { result } = renderHook(() => useCurveTemplates());
    await waitFor(() => expect(result.current.templates).toEqual(templates));
    expect(mockApi.getCurveTemplates).toHaveBeenCalledTimes(1);

    await act(async () => result.current.createTemplate('Warmup', []));
    await act(async () => result.current.updateTemplate(4, 'New name', []));
    await act(async () => result.current.deleteTemplate(4));

    expect(mockApi.createCurveTemplate).toHaveBeenCalledWith('Warmup', []);
    expect(mockApi.updateCurveTemplate).toHaveBeenCalledWith(4, 'New name', []);
    expect(mockApi.deleteCurveTemplate).toHaveBeenCalledWith(4);
    expect(mockApi.getCurveTemplates).toHaveBeenCalledTimes(4);
  });

  it('keeps a failed mutation available to the owning UI for error handling', async () => {
    const failure = new Error('save failed');
    mockApi.createCurveTemplate.mockRejectedValueOnce(failure);
    const { result } = renderHook(() => useCurveTemplates());
    await waitFor(() => expect(result.current.templates).toEqual(templates));

    await expect(result.current.createTemplate('Broken', [])).rejects.toBe(failure);
    expect(mockApi.getCurveTemplates).toHaveBeenCalledTimes(1);
  });

  it('keeps a successful create successful when the list refresh fails and retries only the read', async () => {
    const refreshed = { builtin: [], user: [savedTemplate] };
    const refreshFailure = new Error('list temporarily unavailable');
    const { result } = renderHook(() => useCurveTemplates());
    await waitFor(() => expect(result.current.templates).toEqual(templates));
    mockApi.getCurveTemplates
      .mockRejectedValueOnce(refreshFailure)
      .mockResolvedValueOnce(refreshed);

    await act(async () => {
      await result.current.createTemplate('Saved', []);
    });

    expect(result.current.templates).toEqual(refreshed);
    expect(result.current.refreshError).toContain('list temporarily unavailable');
    expect(mockApi.createCurveTemplate).toHaveBeenCalledTimes(1);

    await act(async () => result.current.refreshTemplates());

    expect(result.current.templates).toEqual(refreshed);
    expect(result.current.refreshError).toBeNull();
    expect(mockApi.createCurveTemplate).toHaveBeenCalledTimes(1);
  });

  it('retains the confirmed update locally when refreshing the list fails', async () => {
    const updated = { id: 4, name: 'Updated', points: [] };
    const { result } = renderHook(() => useCurveTemplates());
    await waitFor(() => expect(result.current.templates).toEqual(templates));
    mockApi.updateCurveTemplate.mockResolvedValueOnce(updated);
    mockApi.getCurveTemplates.mockRejectedValueOnce(new Error('list unavailable'));

    await act(async () => result.current.updateTemplate(4, 'Updated', []));

    expect(result.current.templates?.user).toEqual([updated]);
    expect(result.current.refreshError).toContain('list unavailable');
    expect(mockApi.updateCurveTemplate).toHaveBeenCalledTimes(1);
  });

  it('removes a confirmed delete locally when refreshing the list fails', async () => {
    const original = { id: 4, name: 'Original', points: [] };
    const { result } = renderHook(() => useCurveTemplates());
    await waitFor(() => expect(result.current.templates).toEqual(templates));
    mockApi.getCurveTemplates.mockResolvedValueOnce({ builtin: [], user: [original] });
    await act(async () => result.current.refreshTemplates());
    mockApi.getCurveTemplates.mockRejectedValueOnce(new Error('list unavailable'));

    await act(async () => result.current.deleteTemplate(4));

    expect(result.current.templates?.user).toEqual([]);
    expect(result.current.refreshError).toContain('list unavailable');
    expect(mockApi.deleteCurveTemplate).toHaveBeenCalledWith(4);
  });
});
