'use client';

import type { ReactNode } from 'react';
import { ThemeToggle } from '@/components/ThemeToggle';
import { HelpButton } from '@/components/help/HelpButton';

interface PageControlsProps {
  /** Help page id; when set, the help button (and its tour) is shown. */
  helpPage?: string;
  /** Page-specific controls, rendered before the shared ones. */
  children?: ReactNode;
}

/**
 * The one top-right control row for a page: page-specific toggles, then the
 * theme toggle, then help. It sits in normal flow above the page header, so the
 * controls can never overlap each other or the header (#863).
 */
export function PageControls({ helpPage, children }: PageControlsProps) {
  return (
    <div className="page-controls" role="toolbar" aria-label="Page controls">
      {children}
      <ThemeToggle />
      {helpPage && <HelpButton page={helpPage} />}
    </div>
  );
}
