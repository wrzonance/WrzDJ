'use client';

import sharedStyles from '../setbuilder-shared.module.css';
import importStyles from '../setbuilder-import.module.css';
import ImportEvent from './import/ImportEventFlow';
import ImportPlaylist from './import/ImportPlaylistFlow';
import ImportPublicUrl from './import/ImportPublicUrlFlow';
import ImportManual from './import/ImportManualFlow';
import type { ImportModalProps } from './import/ImportModalShared';
export type { ImportKind } from './import/ImportModalShared';

export default function ImportModal(props: ImportModalProps) {
  return (
    <div className={sharedStyles.modalWrap} role="dialog" aria-modal="true">
      <div className={sharedStyles.modalBackdrop} onClick={props.onClose} />
      <div className={importStyles.importModal}>
        {props.kind === 'event' && <ImportEvent {...props} />}
        {(props.kind === 'tidal' || props.kind === 'beatport') && <ImportPlaylist {...props} />}
        {props.kind === 'public_url' && <ImportPublicUrl {...props} />}
        {props.kind === 'manual' && <ImportManual {...props} />}
      </div>
    </div>
  );
}
