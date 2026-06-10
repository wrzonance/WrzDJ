import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import AdminAISettingsPage from '../page';
import { api } from '@/lib/api';
import type {
  AISettings,
  LlmAdminAudit,
  LlmAdminConnector,
  LlmAdminPolicy,
  LlmAdminUsage,
  LlmConnector,
  LlmDjStatus,
} from '@/lib/api-types';

vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isLoading: false,
    role: 'admin',
    logout: vi.fn(),
  }),
}));

vi.mock('@/lib/help/HelpContext', () => ({
  useHelp: () => ({
    helpMode: false,
    onboardingActive: false,
    currentStep: 0,
    activeSpotId: null,
    toggleHelpMode: vi.fn(),
    registerSpot: vi.fn(() => vi.fn()),
    getSpotsForPage: vi.fn(() => []),
    startOnboarding: vi.fn(),
    nextStep: vi.fn(),
    prevStep: vi.fn(),
    skipOnboarding: vi.fn(),
    hasSeenPage: vi.fn(() => true),
  }),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => '/admin/ai',
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const baseSettings: AISettings = {
  llm_enabled: true,
  llm_rate_limit_per_minute: 3,
};

const basePolicy: LlmAdminPolicy = {
  llm_apikey_connectors_enabled: true,
  llm_compatible_connector_enabled: true,
  llm_default_connector_id: null,
  llm_call_log_retention_days: 30,
};

const emptyAudit: LlmAdminAudit = { rows: [], total: 0, limit: 50, offset: 0 };
const emptyUsage: LlmAdminUsage = { days: 30, rows: [] };
const emptyDjStatus: LlmDjStatus = { rows: [] };

function adminConnector(overrides: Partial<LlmAdminConnector> = {}): LlmAdminConnector {
  return {
    id: 1,
    user_id: 42,
    scope: 'user',
    dj_username: 'someDJ',
    connector_type: 'openai_apikey',
    display_name: 'My OpenAI',
    status: 'active',
    base_url_plain: null,
    model_hint: 'gpt-5-mini',
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
    last_used_at: null,
    last_error: null,
    is_default: false,
    last_health_check_at: null,
    last_health_check_status: null,
    monthly_token_cap: null,
    current_month_tokens: 0,
    ...overrides,
  };
}

function orgConnector(overrides: Partial<LlmConnector> = {}): LlmConnector {
  return {
    id: 50,
    user_id: null,
    scope: 'org',
    connector_type: 'openai_apikey',
    display_name: 'House OpenAI',
    status: 'active',
    base_url_plain: null,
    model_hint: 'gpt-5-mini',
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
    last_used_at: null,
    last_error: null,
    is_default: false,
    last_health_check_at: null,
    last_health_check_status: null,
    monthly_token_cap: null,
    ...overrides,
  };
}

/**
 * Mock every API call the page makes on mount with sensible defaults.
 * Individual tests re-spy specific methods to override.
 */
function mockApis(
  overrides: {
    settings?: AISettings;
    policy?: LlmAdminPolicy;
    connectors?: LlmAdminConnector[];
    usage?: LlmAdminUsage;
    orgConnectors?: LlmConnector[];
    djStatus?: LlmDjStatus;
    audit?: LlmAdminAudit;
  } = {},
) {
  vi.spyOn(api, 'getAISettings').mockResolvedValue(overrides.settings ?? baseSettings);
  vi.spyOn(api, 'getAdminLlmPolicy').mockResolvedValue(overrides.policy ?? basePolicy);
  vi.spyOn(api, 'listAllLlmConnectors').mockResolvedValue(overrides.connectors ?? []);
  vi.spyOn(api, 'getAdminLlmUsage').mockResolvedValue(overrides.usage ?? emptyUsage);
  vi.spyOn(api, 'listOrgConnectors').mockResolvedValue(overrides.orgConnectors ?? []);
  vi.spyOn(api, 'getDjLlmStatus').mockResolvedValue(overrides.djStatus ?? emptyDjStatus);
  vi.spyOn(api, 'getAdminLlmAudit').mockResolvedValue(overrides.audit ?? emptyAudit);
}

describe('AdminAISettingsPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders loading state initially', () => {
    mockApis();
    vi.spyOn(api, 'getAISettings').mockImplementation(() => new Promise(() => {}));

    render(<AdminAISettingsPage />);
    expect(screen.getByText('Loading AI settings...')).toBeInTheDocument();
  });

  it('renders settings after load without the legacy API Key Status panel', async () => {
    mockApis();

    render(<AdminAISettingsPage />);

    await waitFor(() => {
      expect(screen.getByText('AI / LLM Settings')).toBeInTheDocument();
    });

    // Legacy env-var key panel and model selector are gone.
    expect(screen.queryByText('API Key Status')).not.toBeInTheDocument();
    expect(screen.queryByText('Configured')).not.toBeInTheDocument();
    expect(screen.queryByText('Not Configured')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Model')).not.toBeInTheDocument();
  });

  it('renders the fallback toggle with org-fallback copy', async () => {
    mockApis();

    render(<AdminAISettingsPage />);

    await waitFor(() => {
      expect(
        screen.getByText(
          /Allow DJs without their own connector to use the organization connector/i,
        ),
      ).toBeInTheDocument();
    });
  });

  it('calls updateAISettings on save', async () => {
    mockApis();
    const updateSpy = vi.spyOn(api, 'updateAISettings').mockResolvedValue(baseSettings);

    render(<AdminAISettingsPage />);

    await waitFor(() => {
      expect(screen.getByText('Save Settings')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Save Settings'));

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith({
        llm_enabled: true,
        llm_rate_limit_per_minute: 3,
      });
    });
  });

  it('shows error on fetch failure', async () => {
    mockApis();
    vi.spyOn(api, 'getAISettings').mockRejectedValue(new Error('Network error'));

    render(<AdminAISettingsPage />);

    await waitFor(() => {
      expect(screen.getByText('Failed to load AI settings')).toBeInTheDocument();
    });
  });

  it('renders connector policy + per-DJ connector cards when gateway data loads', async () => {
    mockApis({ connectors: [adminConnector()] });

    render(<AdminAISettingsPage />);

    await waitFor(() =>
      expect(screen.getByText('Connector policy')).toBeInTheDocument(),
    );
    expect(screen.getByText('Per-DJ connectors')).toBeInTheDocument();
    expect(screen.getByText('someDJ')).toBeInTheDocument();
    expect(screen.getByText(/Usage — last 30 days/)).toBeInTheDocument();
  });

  // -------- org-scoped house connector --------

  it('renders the Organization connector section', async () => {
    mockApis();

    render(<AdminAISettingsPage />);

    await waitFor(() =>
      expect(screen.getByText('Organization connector')).toBeInTheDocument(),
    );
  });

  it('shows a create form in the empty state and creates an org connector on submit', async () => {
    mockApis();
    const createSpy = vi.spyOn(api, 'createOrgConnector').mockResolvedValue(orgConnector());

    render(<AdminAISettingsPage />);

    await waitFor(() =>
      expect(screen.getByText('Organization connector')).toBeInTheDocument(),
    );
    // Empty-state explainer
    expect(screen.getByText(/house credential/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Display name'), {
      target: { value: 'House key' },
    });
    fireEvent.change(screen.getByLabelText('API key'), {
      target: { value: 'sk-test-123' },
    });
    fireEvent.change(screen.getByLabelText('Model hint (optional)'), {
      target: { value: 'gpt-5-mini' },
    });
    fireEvent.click(screen.getByText('Add connector'));

    await waitFor(() =>
      expect(createSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          connector_type: 'openai_apikey',
          display_name: 'House key',
          api_key: 'sk-test-123',
          model_hint: 'gpt-5-mini',
        }),
      ),
    );
  });

  it('lists an existing org connector with Test and Delete actions', async () => {
    mockApis({ orgConnectors: [orgConnector()] });
    const testSpy = vi.spyOn(api, 'testOrgConnector').mockResolvedValue({
      ok: true,
      message: 'Connection OK',
      error_code: null,
    });
    const deleteSpy = vi.spyOn(api, 'deleteOrgConnector').mockResolvedValue(undefined);
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<AdminAISettingsPage />);

    await waitFor(() => expect(screen.getByText('House OpenAI')).toBeInTheDocument());
    expect(screen.getByText('Active')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Test'));
    await waitFor(() => expect(testSpy).toHaveBeenCalledWith(50));

    fireEvent.click(screen.getByText('Delete'));
    await waitFor(() => expect(deleteSpy).toHaveBeenCalledWith(50));
  });

  it('renders the org API key input as a password field', async () => {
    mockApis();

    render(<AdminAISettingsPage />);

    await waitFor(() => expect(screen.getByLabelText('API key')).toBeInTheDocument());
    expect(screen.getByLabelText('API key')).toHaveAttribute('type', 'password');
  });

  it('shows an error and retains the typed key when org connector creation fails', async () => {
    mockApis();
    vi.spyOn(api, 'createOrgConnector').mockRejectedValue(new Error('Invalid API key'));

    render(<AdminAISettingsPage />);

    await waitFor(() =>
      expect(screen.getByText('Organization connector')).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByLabelText('Display name'), {
      target: { value: 'House key' },
    });
    fireEvent.change(screen.getByLabelText('API key'), {
      target: { value: 'sk-bad' },
    });
    fireEvent.click(screen.getByText('Add connector'));

    await waitFor(() => expect(screen.getByText('Invalid API key')).toBeInTheDocument());
    // Inputs keep their values so the admin can correct and retry.
    expect((screen.getByLabelText('API key') as HTMLInputElement).value).toBe('sk-bad');
    expect((screen.getByLabelText('Display name') as HTMLInputElement).value).toBe('House key');
  });

  it('renders per-DJ effective-source badges from dj-status', async () => {
    mockApis({
      djStatus: {
        rows: [
          { user_id: 1, username: 'djtest', effective_source: 'org_fallback' },
          { user_id: 2, username: 'djown', effective_source: 'own' },
          { user_id: 3, username: 'djnone', effective_source: 'none' },
        ],
      },
    });

    render(<AdminAISettingsPage />);

    await waitFor(() => expect(screen.getByText('djtest')).toBeInTheDocument());
    expect(screen.getByText('Org fallback')).toBeInTheDocument();
    expect(screen.getByText('djown')).toBeInTheDocument();
    expect(screen.getByText('Own connector')).toBeInTheDocument();
    expect(screen.getByText('djnone')).toBeInTheDocument();
    expect(screen.getByText('None — AI unavailable')).toBeInTheDocument();
  });

  it('offers only org-scoped connectors in the org-default dropdown', async () => {
    mockApis({
      connectors: [adminConnector({ display_name: 'My OpenAI' })],
      orgConnectors: [orgConnector({ display_name: 'House OpenAI' })],
    });

    render(<AdminAISettingsPage />);

    await waitFor(() =>
      expect(screen.getByLabelText('Org default connector')).toBeInTheDocument(),
    );
    const select = screen.getByLabelText('Org default connector');
    expect(
      within(select).getByText('Organization — House OpenAI (OpenAI)'),
    ).toBeInTheDocument();
    expect(within(select).queryByText(/My OpenAI/)).not.toBeInTheDocument();
  });

  // -------- audit trail --------

  it('renders the audit trail card with seeded events', async () => {
    mockApis({
      audit: {
        rows: [
          {
            id: 1,
            created_at: '2026-05-20T12:00:00Z',
            event_type: 'connector_created',
            actor_user_id: 42,
            actor_username: 'someDJ',
            target_connector_id: 7,
            target_connector_display_name: 'My OpenAI',
            notes: null,
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      },
    });

    render(<AdminAISettingsPage />);

    await waitFor(() =>
      expect(screen.getByText('Audit trail')).toBeInTheDocument(),
    );
    expect(screen.getByText('connector_created')).toBeInTheDocument();
    expect(screen.getByText('My OpenAI')).toBeInTheDocument();
    // someDJ appears in the audit row (no connectors table rows to collide)
    expect(screen.getByText('someDJ')).toBeInTheDocument();
    // Filter + export controls
    expect(screen.getByLabelText('Event type')).toBeInTheDocument();
    expect(screen.getByText('Export CSV')).toBeInTheDocument();
  });

  it('refetches audit events when the event-type filter changes', async () => {
    mockApis();
    const auditSpy = vi.spyOn(api, 'getAdminLlmAudit').mockResolvedValue(emptyAudit);
    const exportSpy = vi
      .spyOn(api, 'downloadAdminLlmAuditCsv')
      .mockResolvedValue(new Blob(['ok'], { type: 'text/csv' }));
    // jsdom doesn't implement these — handleExportCsv triggers a browser download.
    const createObjectURL = vi.fn(() => 'blob:mock');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL });

    try {
      render(<AdminAISettingsPage />);

      await waitFor(() => expect(screen.getByText('Audit trail')).toBeInTheDocument());
      auditSpy.mockClear();

      fireEvent.change(screen.getByLabelText('Event type'), {
        target: { value: 'connector_credentials_rotated' },
      });

      await waitFor(() =>
        expect(auditSpy).toHaveBeenCalledWith(
          expect.objectContaining({ event_type: 'connector_credentials_rotated' }),
        ),
      );

      // CSV export must honor the active event-type filter.
      fireEvent.click(screen.getByText('Export CSV'));
      await waitFor(() =>
        expect(exportSpy).toHaveBeenCalledWith(
          expect.objectContaining({ event_type: 'connector_credentials_rotated' }),
        ),
      );
    } finally {
      // Guarantee the URL stub is restored even if an assertion fails early,
      // so it can't leak into later tests.
      vi.unstubAllGlobals();
    }
  });

  it('force-revokes a connector via the admin table', async () => {
    mockApis({
      connectors: [
        adminConnector({ id: 9, dj_username: 'badDJ', display_name: 'Compromised' }),
      ],
    });
    const revokeSpy = vi.spyOn(api, 'revokeAdminLlmConnector').mockResolvedValue(
      adminConnector({
        id: 9,
        dj_username: 'badDJ',
        display_name: 'Compromised',
        status: 'disabled',
      }),
    );
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<AdminAISettingsPage />);

    await waitFor(() => expect(screen.getByText('Compromised')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Force-revoke'));
    await waitFor(() => expect(revokeSpy).toHaveBeenCalledWith(9));
  });

  it('persists call-log retention on blur via the policy patch (issue #342)', async () => {
    mockApis();
    const patchSpy = vi.spyOn(api, 'updateAdminLlmPolicy').mockResolvedValue({
      ...basePolicy,
      llm_call_log_retention_days: 90,
    });

    render(<AdminAISettingsPage />);

    const input = (await screen.findByLabelText(
      /Call log retention/i,
    )) as HTMLInputElement;
    expect(input.value).toBe('30');

    fireEvent.change(input, { target: { value: '90' } });
    fireEvent.blur(input);

    await waitFor(() =>
      expect(patchSpy).toHaveBeenCalledWith(
        expect.objectContaining({ llm_call_log_retention_days: 90 }),
      ),
    );
  });

  it('clamps an out-of-range retention value before patching (issue #342)', async () => {
    mockApis();
    const patchSpy = vi.spyOn(api, 'updateAdminLlmPolicy').mockResolvedValue({
      ...basePolicy,
      llm_call_log_retention_days: 365,
    });

    render(<AdminAISettingsPage />);

    const input = (await screen.findByLabelText(
      /Call log retention/i,
    )) as HTMLInputElement;
    fireEvent.change(input, { target: { value: '9999' } });
    fireEvent.blur(input);

    await waitFor(() =>
      expect(patchSpy).toHaveBeenCalledWith(
        expect.objectContaining({ llm_call_log_retention_days: 365 }),
      ),
    );
  });

  // Use 5 (not 0) for the below-min value: the onChange handler treats a falsy
  // parsed value as "no change" (`parseInt(...) || policy.value`), so 0 would be
  // coerced back to the current policy before blur ever sees it. 5 is a genuine
  // below-min entry that the blur clamp must lift to 7.
  it('clamps a below-min retention value before patching (issue #342)', async () => {
    mockApis();
    const patchSpy = vi.spyOn(api, 'updateAdminLlmPolicy').mockResolvedValue({
      ...basePolicy,
      llm_call_log_retention_days: 7,
    });

    render(<AdminAISettingsPage />);

    const input = (await screen.findByLabelText(
      /Call log retention/i,
    )) as HTMLInputElement;
    fireEvent.change(input, { target: { value: '5' } });
    fireEvent.blur(input);

    await waitFor(() =>
      expect(patchSpy).toHaveBeenCalledWith(
        expect.objectContaining({ llm_call_log_retention_days: 7 }),
      ),
    );
  });

  // -------- issue #346: surface health-check columns in connectors table --------
  it('renders last-health-check column with a status badge per connector', async () => {
    mockApis({
      connectors: [
        adminConnector({
          id: 1,
          user_id: 1,
          dj_username: 'alpha',
          display_name: 'Alpha key',
          model_hint: null,
          last_health_check_at: '2026-05-28T10:00:00Z',
          last_health_check_status: 'ok',
        }),
        adminConnector({
          id: 2,
          user_id: 2,
          dj_username: 'bravo',
          connector_type: 'anthropic_apikey',
          display_name: 'Bravo key',
          status: 'auth_invalid',
          model_hint: null,
          last_error: 'auth_invalid',
          last_health_check_at: '2026-05-28T09:00:00Z',
          last_health_check_status: 'auth_invalid',
        }),
        adminConnector({
          id: 3,
          user_id: 3,
          dj_username: 'charlie',
          display_name: 'Charlie key',
          model_hint: null,
          last_health_check_at: null,
          last_health_check_status: null,
        }),
      ],
    });

    render(<AdminAISettingsPage />);

    await waitFor(() => expect(screen.getByText('Alpha key')).toBeInTheDocument());
    // Column header rendered with sortable affordance
    expect(screen.getByText('Last health check')).toBeInTheDocument();
    // Each badge visible
    expect(screen.getByText('OK')).toBeInTheDocument();
    expect(screen.getByText('Auth invalid')).toBeInTheDocument();
    expect(screen.getByText('Never checked')).toBeInTheDocument();
  });

  it('toggles sort direction when clicking the last-health-check header', async () => {
    mockApis({
      connectors: [
        adminConnector({
          id: 1,
          user_id: 1,
          dj_username: 'older',
          display_name: 'Older check',
          model_hint: null,
          last_health_check_at: '2026-05-01T00:00:00Z',
          last_health_check_status: 'ok',
        }),
        adminConnector({
          id: 2,
          user_id: 2,
          dj_username: 'newer',
          display_name: 'Newer check',
          model_hint: null,
          last_health_check_at: '2026-05-28T00:00:00Z',
          last_health_check_status: 'ok',
        }),
      ],
    });

    render(<AdminAISettingsPage />);

    await waitFor(() => expect(screen.getByText('Newer check')).toBeInTheDocument());

    const findRow = (text: string) => {
      const td = screen.getByText(text);
      const tr = td.closest('tr');
      if (!tr) throw new Error(`row for ${text} not found`);
      return tr;
    };

    // Default sort = last_health_check_at DESC → newer first.
    const tbody = findRow('Newer check').parentElement!;
    const beforeRows = Array.from(tbody.querySelectorAll('tr'));
    const beforeOrder = beforeRows.map((r) => r.querySelector('td')!.textContent);
    expect(beforeOrder).toEqual(['newer', 'older']);

    // Click the Last health check header → should flip to ASC (older first).
    fireEvent.click(screen.getByText('Last health check'));
    await waitFor(() => {
      const rows = Array.from(tbody.querySelectorAll('tr'));
      const order = rows.map((r) => r.querySelector('td')!.textContent);
      expect(order).toEqual(['older', 'newer']);
    });
  });
});
