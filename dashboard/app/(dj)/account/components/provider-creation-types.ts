import type { LlmConnectorType } from '@/lib/api/types';

export interface ProviderFormState {
  open: boolean;
  connector_type: LlmConnectorType;
  display_name: string;
  api_key: string;
  base_url: string;
  bearer: string;
  model_hint: string;
  aws_access_key_id: string;
  aws_secret_access_key: string;
  aws_region: string;
  aws_model_id: string;
  azure_resource_name: string;
  azure_deployment_name: string;
  azure_api_version: string;
}

export type ProviderFormField = Exclude<keyof ProviderFormState, 'open' | 'connector_type'>;
