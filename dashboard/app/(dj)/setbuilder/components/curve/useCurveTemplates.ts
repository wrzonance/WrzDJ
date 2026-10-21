import { useCallback, useEffect, useState } from 'react';
import { api } from '@/lib/api';
import type { CurvePoint, CurveTemplatesResponse } from '@/lib/api/types';

export function useCurveTemplates() {
  const [templates, setTemplates] = useState<CurveTemplatesResponse | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const refreshTemplates = useCallback(async () => {
    try {
      const response = await api.getCurveTemplates();
      setTemplates(response);
      setRefreshError(null);
      return response;
    } catch (cause) {
      setRefreshError(
        cause instanceof Error && cause.message
          ? cause.message
          : 'Could not load curve templates. Please try again.',
      );
      throw cause;
    }
  }, []);

  useEffect(() => {
    void refreshTemplates().catch(() => undefined);
  }, [refreshTemplates]);

  const createTemplate = useCallback(
    async (name: string, points: CurvePoint[]) => {
      const created = await api.createCurveTemplate(name, points);
      setTemplates((current) => ({
        builtin: current?.builtin ?? [],
        user: [...(current?.user ?? []).filter((template) => template.id !== created.id), created],
      }));
      await refreshTemplates().catch(() => undefined);
      return created;
    },
    [refreshTemplates],
  );

  const updateTemplate = useCallback(
    async (templateId: number, name: string, points: CurvePoint[]) => {
      const updated = await api.updateCurveTemplate(templateId, name, points);
      setTemplates((current) => ({
        builtin: current?.builtin ?? [],
        user: [...(current?.user ?? []).filter((template) => template.id !== updated.id), updated],
      }));
      await refreshTemplates().catch(() => undefined);
      return updated;
    },
    [refreshTemplates],
  );

  const deleteTemplate = useCallback(
    async (templateId: number) => {
      await api.deleteCurveTemplate(templateId);
      setTemplates((current) => ({
        builtin: current?.builtin ?? [],
        user: (current?.user ?? []).filter((template) => template.id !== templateId),
      }));
      await refreshTemplates().catch(() => undefined);
    },
    [refreshTemplates],
  );

  return { templates, refreshError, refreshTemplates, createTemplate, updateTemplate, deleteTemplate };
}
