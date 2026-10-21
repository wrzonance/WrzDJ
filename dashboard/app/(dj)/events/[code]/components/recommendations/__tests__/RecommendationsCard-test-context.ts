import type { Mock } from 'vitest';
import type {
  LLMRecommendationResponse,
  PlaylistInfo,
  RecommendedTrack,
  RecommendationResponse,
} from '@/lib/api/types';

export interface RecommendationsCardTestContext {
  api: typeof import('@/lib/api').api;
  RecommendationsCard: typeof import('../RecommendationsCard').RecommendationsCard;
  makeSuggestion: (overrides?: Partial<RecommendedTrack>) => RecommendedTrack;
  makeResponse: (overrides?: Partial<RecommendationResponse>) => RecommendationResponse;
  makeLLMResponse: (
    overrides?: Partial<LLMRecommendationResponse>,
  ) => LLMRecommendationResponse;
  makePlaylist: (overrides?: Partial<PlaylistInfo>) => PlaylistInfo;
  defaultProps: {
    code: string;
    hasAcceptedRequests: boolean;
    tidalLinked: boolean;
    beatportLinked: boolean;
    onAcceptTrack: Mock;
  };
}
