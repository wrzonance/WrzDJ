import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { api } from '@/lib/api';
import type { VibeWindowView, SlotView } from '../types';
import type { BuilderCommit } from '../useSetDocumentHistory';
import type { ConfirmAction } from '../ConfirmActionDialog';
import type { TemplateDraft } from './CurveTemplateEditorOverlay';
import { slotMidpoints } from './curveMath';
import { useCurveTemplates } from './useCurveTemplates';

export interface TemplateEditorState {
  open: boolean;
  mode: 'create' | 'edit';
  initial: TemplateDraft | null;
  isBuiltIn: boolean;
}

const CLOSED_EDITOR: TemplateEditorState = {
  open: false,
  mode: 'create',
  initial: null,
  isBuiltIn: false,
};

interface CurveTemplateManagementOptions {
  setId: number;
  slots: SlotView[];
  totalSec: number;
  confirmRecompute: boolean;
  requestConfirmation?: (action: ConfirmAction) => Promise<boolean>;
  commit?: BuilderCommit;
  onSlotsChange: (updater: (previous: SlotView[]) => SlotView[]) => void;
  replaceWindows: (windows: VibeWindowView[]) => void;
  clearReplacementPrompt: () => void;
}

export function useCurveTemplateManagement({
  setId,
  slots,
  totalSec,
  confirmRecompute,
  requestConfirmation,
  commit,
  onSlotsChange,
  replaceWindows,
  clearReplacementPrompt,
}: CurveTemplateManagementOptions) {
  const apiTemplates = useCurveTemplates();
  const { templates, refreshError, refreshTemplates } = apiTemplates;
  const [activeTemplateName, setActiveTemplateName] = useState<string | null>(null);
  const [editor, setEditor] = useState<TemplateEditorState>(CLOSED_EDITOR);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [mutationPending, setMutationPending] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const activeScope = useRef({ setId, generation: 0 });
  const editorSession = useRef(0);
  const mounted = useRef(true);

  useLayoutEffect(() => {
    if (activeScope.current.setId !== setId) {
      activeScope.current = { setId, generation: activeScope.current.generation + 1 };
    }
  }, [setId]);

  useEffect(() => {
    editorSession.current += 1;
    setActiveTemplateName(null);
    setEditor(CLOSED_EDITOR);
    setMutationError(null);
    setApplyError(null);
  }, [setId]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const openEditor = (name: string, isBuiltIn: boolean) => {
    if (isBuiltIn) {
      const template = templates?.builtin.find((item) => item.name === name);
      if (!template) return;
      editorSession.current += 1;
      setMutationError(null);
      setEditor({
        open: true,
        mode: 'edit',
        isBuiltIn: true,
        initial: { name: template.name, points: template.points },
      });
      return;
    }

    const template = templates?.user.find((item) => item.name === name);
    if (!template) return;
    editorSession.current += 1;
    setMutationError(null);
    setEditor({
      open: true,
      mode: 'edit',
      isBuiltIn: false,
      initial: { id: template.id, name: template.name, points: template.points },
    });
  };

  const runMutation = async (operation: () => Promise<unknown>): Promise<boolean> => {
    const requestScope = activeScope.current;
    const requestEditorSession = editorSession.current;
    setMutationError(null);
    setMutationPending(true);
    try {
      await operation();
      return true;
    } catch (cause) {
      if (
        mounted.current &&
        activeScope.current === requestScope &&
        editorSession.current === requestEditorSession
      ) {
        setMutationError(
          cause instanceof Error && cause.message ? cause.message : 'Template update failed',
        );
      }
      return false;
    } finally {
      if (mounted.current) setMutationPending(false);
    }
  };

  const saveNew = (draft: TemplateDraft) =>
    runMutation(() => apiTemplates.createTemplate(draft.name, draft.points));
  const saveCurrent = (draft: TemplateDraft) => {
    const templateId = draft.id;
    if (templateId == null) return Promise.resolve(false);
    return runMutation(() => apiTemplates.updateTemplate(templateId, draft.name, draft.points));
  };
  const remove = (templateId: number) =>
    runMutation(() => apiTemplates.deleteTemplate(templateId));

  const openNewEditor = () => {
    editorSession.current += 1;
    setMutationError(null);
    setEditor({ open: true, mode: 'create', initial: null, isBuiltIn: false });
  };

  const closeEditor = () => {
    editorSession.current += 1;
    setMutationError(null);
    setEditor(CLOSED_EDITOR);
  };

  const applyTemplate = async (
    source: { builtin?: string; template_id?: number },
    name: string,
  ) => {
    const requestScope = activeScope.current;
    setApplyError(null);
    if (confirmRecompute && requestConfirmation) {
      const ok = await requestConfirmation({
        title: 'Recompute curve targets?',
        body: (
          <>
            <p>This reruns builder placement against the current curve, pool, and pairings.</p>
            <ul>
              <li>
                {slots.filter((slot) => slot.locked).length} locked{' '}
                {slots.filter((slot) => slot.locked).length === 1 ? 'slot stays' : 'slots stay'} put.
              </li>
              <li>
                {Math.max(0, slots.length - slots.filter((slot) => slot.locked).length)} unlocked{' '}
                {Math.max(0, slots.length - slots.filter((slot) => slot.locked).length) === 1
                  ? 'slot may'
                  : 'slots may'}{' '}
                reorder and overwrite manual order changes.
              </li>
              <li>Saved pairings are weighted during placement.</li>
              <li>The action is undoable from the topbar or with Ctrl/Cmd+Z.</li>
            </ul>
          </>
        ),
        confirmLabel: 'Yes, recompute',
        kind: 'warning',
      });
      if (!ok) return;
    }
    if (
      !mounted.current ||
      activeScope.current.setId !== requestScope.setId ||
      activeScope.current.generation !== requestScope.generation
    ) return;

    const midpoints = slots.length > 0 ? slotMidpoints(slots) : undefined;
    const save = async () => {
      const response = await api.applyCurveTemplate(setId, source, midpoints);
      if (totalSec > 0) {
        await api.putVibeWindows(
          setId,
          response.windows.map((window) => ({
            t0_sec: Math.round(window.t0 * totalSec),
            t1_sec: Math.max(Math.round(window.t0 * totalSec) + 1, Math.round(window.t1 * totalSec)),
            label: 'Slow set',
          })),
        );
      }
      return response;
    };
    const run = commit ? commit(`Apply curve ${name}`, save) : save();
    run
      .then((response) => {
        if (
          !mounted.current ||
          activeScope.current.setId !== requestScope.setId ||
          activeScope.current.generation !== requestScope.generation
        ) return;
        const targetBySlotId = new Map(
          response.targets.map((target) => [target.slot_id, target.target_energy]),
        );
        onSlotsChange((previous) =>
          previous.map((slot) =>
            targetBySlotId.has(slot.id)
              ? { ...slot, targetEnergy: targetBySlotId.get(slot.id) ?? null }
              : slot,
          ),
        );
        replaceWindows(
          response.windows.map((window, index) => ({
            id: `tw-${index}-${window.t0}`,
            t0: window.t0,
            t1: window.t1,
            label: 'Slow set',
          })),
        );
        setActiveTemplateName(name);
        clearReplacementPrompt();
      })
      .catch((cause: unknown) => {
        if (mounted.current && activeScope.current === requestScope) {
          setApplyError(
            cause instanceof Error && cause.message ? cause.message : 'Could not apply curve template',
          );
        }
      });
  };

  return {
    templates,
    refreshError,
    refreshTemplates,
    activeTemplateName,
    editor,
    mutationError,
    mutationPending,
    applyError,
    openEditor,
    openNewEditor,
    closeEditor,
    saveNew,
    saveCurrent,
    remove,
    applyTemplate,
  };
}
