'use client';

import { CollectionFormFields, type CollectionFormFieldsProps } from './CollectionFormFields';

export { collectionSchema } from './CollectionFormFields';

export interface CollectionFieldsetProps extends CollectionFormFieldsProps {
  enabled: boolean;
  onEnabledChange: (next: boolean) => void;
}

export function CollectionFieldset(props: CollectionFieldsetProps) {
  const {
    enabled,
    onEnabledChange,
    ...fields
  } = props;

  return (
    <div className="collection-fieldset">
      <label className="collection-fieldset-toggle">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onEnabledChange(e.target.checked)}
        />
        Enable pre-event voting
      </label>

      {enabled && (
        <div className="collection-fieldset-fields">
          <CollectionFormFields {...fields} />
        </div>
      )}
    </div>
  );
}
