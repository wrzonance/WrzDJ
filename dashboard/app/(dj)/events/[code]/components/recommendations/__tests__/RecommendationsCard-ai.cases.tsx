import { it, expect, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { RecommendationsCardTestContext } from './RecommendationsCard-test-context';

export function registerAiTests(context: RecommendationsCardTestContext) {
  const { api, RecommendationsCard, makeSuggestion, makeResponse, makeLLMResponse, defaultProps } = context;


  // AI Assist (LLM) tests

  it('enables AI Assist button when llm_available is true', async () => {
    vi.mocked(api.generateRecommendations).mockResolvedValue(
      makeResponse({ llm_available: true })
    );

    render(<RecommendationsCard {...defaultProps} />);

    // Initially AI Assist button is visible but disabled
    const aiButton = screen.getByText('AI Assist');
    expect(aiButton).toBeInTheDocument();
    expect(aiButton).toBeDisabled();

    // Generate to get llm_available from response
    fireEvent.click(screen.getByText('Generate'));

    await waitFor(() => {
      expect(screen.getByText('AI Assist')).not.toBeDisabled();
    });
  });

  it('keeps AI Assist button disabled when llm_available is false', async () => {
    vi.mocked(api.generateRecommendations).mockResolvedValue(
      makeResponse({ llm_available: false })
    );

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('Generate'));

    await waitFor(() => {
      expect(screen.getByText(/Test Artist/)).toBeInTheDocument();
    });

    const aiButton = screen.getByText('AI Assist');
    expect(aiButton).toBeDisabled();
  });

  it('shows prompt input in AI Assist mode', async () => {
    vi.mocked(api.generateRecommendations).mockResolvedValue(
      makeResponse({ llm_available: true })
    );

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('Generate'));

    await waitFor(() => {
      expect(screen.getByText('AI Assist')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('AI Assist'));

    expect(screen.getByPlaceholderText(/recommend some more/)).toBeInTheDocument();
  });

  it('calls LLM API with prompt when generating in AI Assist mode', async () => {
    vi.mocked(api.generateRecommendations).mockResolvedValue(
      makeResponse({ llm_available: true })
    );
    vi.mocked(api.generateLLMRecommendations).mockResolvedValue(makeLLMResponse());

    render(<RecommendationsCard {...defaultProps} />);

    // First generate to discover llm_available
    fireEvent.click(screen.getByText('Generate'));
    await waitFor(() => {
      expect(screen.getByText('AI Assist')).toBeInTheDocument();
    });

    // Switch to AI Assist mode
    fireEvent.click(screen.getByText('AI Assist'));

    // Type a prompt
    const input = screen.getByPlaceholderText(/recommend some more/);
    fireEvent.change(input, { target: { value: 'dark techno vibes' } });

    // Generate
    fireEvent.click(screen.getByText('Generate'));

    await waitFor(() => {
      expect(api.generateLLMRecommendations).toHaveBeenCalledWith('TEST01', 'dark techno vibes');
    });
  });

  it('shows AI reasoning toggle after LLM generation', async () => {
    vi.mocked(api.generateRecommendations).mockResolvedValue(
      makeResponse({ llm_available: true })
    );
    vi.mocked(api.generateLLMRecommendations).mockResolvedValue(makeLLMResponse());

    render(<RecommendationsCard {...defaultProps} />);

    // Get llm_available
    fireEvent.click(screen.getByText('Generate'));
    await waitFor(() => {
      expect(screen.getByText('AI Assist')).toBeInTheDocument();
    });

    // Switch to LLM mode and generate
    fireEvent.click(screen.getByText('AI Assist'));
    const input = screen.getByPlaceholderText(/recommend some more/);
    fireEvent.change(input, { target: { value: 'dark techno' } });
    fireEvent.click(screen.getByText('Generate'));

    await waitFor(() => {
      expect(screen.getByText(/Show AI reasoning/)).toBeInTheDocument();
    });

    // Click to expand reasoning
    fireEvent.click(screen.getByText(/Show AI reasoning/));

    await waitFor(() => {
      expect(screen.getByText('dark techno')).toBeInTheDocument();
      expect(screen.getByText(/DJ wants darker sounds/)).toBeInTheDocument();
    });
  });

  it('shows Verified Artist badge for mb_verified tracks', async () => {
    vi.mocked(api.generateRecommendations).mockResolvedValue(makeResponse({
      suggestions: [
        makeSuggestion({ title: 'Verified Song', artist: 'Real Artist', mb_verified: true }),
        makeSuggestion({ title: 'Unverified Song', artist: 'Unknown Artist', mb_verified: false }),
      ],
    }));

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('Generate'));

    await waitFor(() => {
      expect(screen.getByText(/Real Artist/)).toBeInTheDocument();
      expect(screen.getByText(/Unknown Artist/)).toBeInTheDocument();
    });

    const badges = screen.getAllByText('Verified Artist');
    expect(badges).toHaveLength(1);
  });

  it('does not show Verified Artist badge when mb_verified is false', async () => {
    vi.mocked(api.generateRecommendations).mockResolvedValue(makeResponse({
      suggestions: [
        makeSuggestion({ mb_verified: false }),
      ],
    }));

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('Generate'));

    await waitFor(() => {
      expect(screen.getByText(/Test Artist/)).toBeInTheDocument();
    });

    expect(screen.queryByText('Verified Artist')).not.toBeInTheDocument();
  });

  it('disables Generate in AI Assist mode when prompt is too short', async () => {
    vi.mocked(api.generateRecommendations).mockResolvedValue(
      makeResponse({ llm_available: true })
    );

    render(<RecommendationsCard {...defaultProps} />);
    fireEvent.click(screen.getByText('Generate'));

    await waitFor(() => {
      expect(screen.getByText('AI Assist')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('AI Assist'));

    // Empty prompt — should be disabled
    expect(screen.getByText('Generate')).toBeDisabled();

    // Two chars — still disabled (min 3)
    const input = screen.getByPlaceholderText(/recommend some more/);
    fireEvent.change(input, { target: { value: 'ab' } });
    expect(screen.getByText('Generate')).toBeDisabled();

    // Three chars — enabled
    fireEvent.change(input, { target: { value: 'abc' } });
    expect(screen.getByText('Generate')).not.toBeDisabled();
  });
}
