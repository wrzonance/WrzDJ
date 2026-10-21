import { registerPlaylistTests } from './RecommendationsCard-playlists.cases';
import { registerAiTests } from './RecommendationsCard-ai.cases';
import { registerLifecycleTests } from './RecommendationsCard-lifecycle.cases';
import type { RecommendationsCardTestContext } from './RecommendationsCard-test-context';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { RecommendationsCard } from '../RecommendationsCard';
import type {
  RecommendedTrack,
  RecommendationResponse,
  PlaylistInfo,
  LLMRecommendationResponse,
} from '@/lib/api/types';

// Mock the api module
vi.mock('@/lib/api', () => ({
  api: {
    generateRecommendations: vi.fn(),
    getEventPlaylists: vi.fn(),
    generateRecommendationsFromTemplate: vi.fn(),
    generateLLMRecommendations: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
}));

import { api } from '@/lib/api';

function makeSuggestion(overrides: Partial<RecommendedTrack> = {}): RecommendedTrack {
  return {
    title: 'Test Track',
    artist: 'Test Artist',
    bpm: 128,
    key: '8A',
    genre: 'Tech House',
    score: 0.92,
    bpm_score: 1.0,
    key_score: 1.0,
    genre_score: 0.8,
    source: 'beatport',
    track_id: '12345',
    url: 'https://beatport.com/track/test/12345',
    cover_url: 'https://bp.com/cover.jpg',
    duration_seconds: 360,
    mb_verified: false,
    ...overrides,
  };
}

function makeResponse(overrides: Partial<RecommendationResponse> = {}): RecommendationResponse {
  return {
    suggestions: [makeSuggestion()],
    profile: {
      avg_bpm: 128,
      bpm_range_low: 120,
      bpm_range_high: 136,
      dominant_keys: ['8A', '9A'],
      dominant_genres: ['Tech House'],
      track_count: 5,
      enriched_count: 5,
    },
    services_used: ['beatport'],
    total_candidates_searched: 20,
    llm_available: false,
    ...overrides,
  };
}

function makeLLMResponse(
  overrides: Partial<LLMRecommendationResponse> = {}
): LLMRecommendationResponse {
  return {
    suggestions: [makeSuggestion()],
    profile: {
      avg_bpm: 128,
      bpm_range_low: 120,
      bpm_range_high: 136,
      dominant_keys: ['8A'],
      dominant_genres: ['Tech House'],
      track_count: 5,
      enriched_count: 5,
    },
    services_used: ['beatport'],
    total_candidates_searched: 15,
    llm_queries: [
      {
        search_query: 'dark techno',
        target_bpm: 130,
        target_key: '8A',
        target_genre: 'Techno',
        reasoning: 'DJ wants darker sounds',
      },
    ],
    llm_available: true,
    llm_model: 'claude-haiku-4-5-20251001',
    ...overrides,
  };
}

function makePlaylist(overrides: Partial<PlaylistInfo> = {}): PlaylistInfo {
  return {
    id: 'playlist-1',
    name: 'My Mix',
    num_tracks: 10,
    description: 'A great mix',
    cover_url: 'https://bp.com/cover.jpg',
    source: 'beatport',
    ...overrides,
  };
}


  const defaultProps = {
    code: 'TEST01',
    hasAcceptedRequests: true,
    tidalLinked: true,
    beatportLinked: true,
    onAcceptTrack: vi.fn().mockResolvedValue(undefined),
  };

const recommendationsCardTestContext: RecommendationsCardTestContext = { api, RecommendationsCard, makeSuggestion, makeResponse, makeLLMResponse, makePlaylist, defaultProps };
describe('RecommendationsCard', () => {


  beforeEach(() => {
    vi.clearAllMocks();
  });


  it('renders Generate button initially', () => {
    render(<RecommendationsCard {...defaultProps} />);
    expect(screen.getByText('Generate')).toBeInTheDocument();
  });

  it('disables Generate when no accepted requests in request mode', () => {
    render(<RecommendationsCard {...defaultProps} hasAcceptedRequests={false} />);
    const btn = screen.getByText('Generate');
    expect(btn).toBeDisabled();
  });

  it('disables Generate when no connected services', () => {
    render(<RecommendationsCard {...defaultProps} tidalLinked={false} beatportLinked={false} />);
    const btn = screen.getByText('Generate');
    expect(btn).toBeDisabled();
    expect(screen.getByText(/link tidal or beatport/i)).toBeInTheDocument();
  });

  it('shows loading state during generation', async () => {
    vi.mocked(api.generateRecommendations).mockResolvedValue(makeResponse());

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('Generate'));

    await waitFor(() => {
      expect(screen.getByText(/Test Artist/)).toBeInTheDocument();
    });
    expect(api.generateRecommendations).toHaveBeenCalledWith('TEST01');
  });

  it('renders suggestion list after generation', async () => {
    vi.mocked(api.generateRecommendations).mockResolvedValue(makeResponse({
      suggestions: [
        makeSuggestion({ title: 'Song A', artist: 'DJ A' }),
        makeSuggestion({ title: 'Song B', artist: 'DJ B' }),
      ],
    }));

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('Generate'));

    await waitFor(() => {
      expect(screen.getByText(/DJ A/)).toBeInTheDocument();
      expect(screen.getByText(/DJ B/)).toBeInTheDocument();
    });
  });

  it('Accept individual removes track from list', async () => {
    vi.mocked(api.generateRecommendations).mockResolvedValue(makeResponse({
      suggestions: [
        makeSuggestion({ title: 'Song A', artist: 'DJ A' }),
        makeSuggestion({ title: 'Song B', artist: 'DJ B' }),
      ],
    }));

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('Generate'));

    await waitFor(() => {
      expect(screen.getByText(/DJ A/)).toBeInTheDocument();
    });

    const acceptButtons = screen.getAllByText('Accept');
    fireEvent.click(acceptButtons[0]);

    await waitFor(() => {
      expect(screen.queryByText(/DJ A/)).not.toBeInTheDocument();
      expect(screen.getByText(/DJ B/)).toBeInTheDocument();
    });

    expect(defaultProps.onAcceptTrack).toHaveBeenCalledTimes(1);
  });

  it('Accept All clears the list', async () => {
    vi.mocked(api.generateRecommendations).mockResolvedValue(makeResponse({
      suggestions: [
        makeSuggestion({ title: 'Song A', artist: 'DJ A' }),
        makeSuggestion({ title: 'Song B', artist: 'DJ B' }),
      ],
    }));

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('Generate'));

    await waitFor(() => {
      expect(screen.getByText('Accept All')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Accept All'));

    await waitFor(() => {
      expect(screen.queryByText(/DJ A/)).not.toBeInTheDocument();
      expect(screen.queryByText(/DJ B/)).not.toBeInTheDocument();
    });

    expect(defaultProps.onAcceptTrack).toHaveBeenCalledTimes(2);
  });

  it('Clear removes suggestions without API call', async () => {
    vi.mocked(api.generateRecommendations).mockResolvedValue(makeResponse());

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('Generate'));

    await waitFor(() => {
      expect(screen.getByText('Clear')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Clear'));

    expect(screen.queryByText('Test Artist')).not.toBeInTheDocument();
    expect(defaultProps.onAcceptTrack).not.toHaveBeenCalled();
  });
  registerPlaylistTests(recommendationsCardTestContext);
  registerAiTests(recommendationsCardTestContext);
  registerLifecycleTests(recommendationsCardTestContext);
});
