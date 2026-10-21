import type { ApiTransport } from '../transport';
import type { Event } from '../types';
import { ApiError, CSRF_HEADER_NAME, CSRF_HEADER_VALUE, getApiUrl } from '../shared';


export class AccountApi {
  constructor(public readonly transport: ApiTransport) {}

  async login(username: string, password: string): Promise<void> {
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);

    // credentials: 'include' lets the browser store the HttpOnly session cookie
    // the API sets on success (#754); this dashboard discards the body token.
    // The CSRF header is what makes the API issue that cookie at all: a cross-site
    // form POST cannot add it, so it cannot plant a session (login CSRF).
    const response = await fetch(`${getApiUrl()}/api/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        [CSRF_HEADER_NAME]: CSRF_HEADER_VALUE,
      },
      body: formData,
      credentials: 'include',
    });

    if (!response.ok) {
      const message = response.status === 401
        ? 'Invalid credentials'
        : response.status === 429
          ? 'Too many attempts. Try again later.'
          : 'Login failed. Please try again.';
      throw new ApiError(message, response.status);
    }

  }

  /** End this browser's dashboard session (clears the cookie; bearer tokens stay valid). */
  async endSession(): Promise<void> {
    await this.transport.fetch<{ status: string }>('/api/auth/session', { method: 'DELETE' });
  }

  async getMe(): Promise<{
    id: number;
    username: string;
    role: string;
    help_pages_seen: string[];
    pending_email: string | null;
    email: string | null;
    frictionless_join_default: boolean;
  }> {
    return this.transport.fetch('/api/auth/me');
  }

  async markHelpPageSeen(page: string): Promise<void> {
    await this.transport.fetch('/api/auth/help-seen', {
      method: 'POST',
      body: JSON.stringify({ page }),
    });
  }

  async changePassword(data: {
    current_password: string;
    new_password: string;
    confirm_new_password: string;
  }): Promise<{ status: string; message: string }> {
    return this.transport.fetch('/api/auth/me/password', {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async requestEmailChange(data: {
    current_password: string;
    new_email: string;
  }): Promise<{ status: string; message: string }> {
    return this.transport.fetch('/api/auth/me/email/request', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async confirmEmailChange(token: string): Promise<{ status: string; message: string }> {
    return this.transport.publicFetch(
      `${getApiUrl()}/api/auth/email/confirm?token=${encodeURIComponent(token)}`
    );
  }

  async getPublicSettings(): Promise<{ registration_enabled: boolean; turnstile_site_key: string }> {
    return this.transport.publicFetch(`${getApiUrl()}/api/auth/settings`);
  }

  async verifyHuman(turnstileToken: string): Promise<{ verified: boolean; expires_in: number }> {
    const res = await fetch(`${getApiUrl()}/api/public/guest/verify-human`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ turnstile_token: turnstileToken }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: 'Request failed' }));
      throw new ApiError(error.detail || 'Verify failed', res.status);
    }
    return res.json();
  }

  // Fast-path probe used by useHumanVerification on page mount. Returns
  // verified=false on any error (network, 5xx) so the caller's fallback to
  // running Turnstile is unconditional and simple.
  async getVerifyStatus(): Promise<{ verified: boolean; expires_in: number }> {
    try {
      const res = await fetch(`${getApiUrl()}/api/public/guest/verify-status`, {
        method: 'GET',
        credentials: 'include',
      });
      if (!res.ok) return { verified: false, expires_in: 0 };
      // Await JSON parse INSIDE the try so a parse failure falls into the
      // catch and still satisfies the fail-closed {verified: false} contract.
      return await res.json();
    } catch {
      return { verified: false, expires_in: 0 };
    }
  }

  // Gated endpoint returning the live event join_code to verified humans.
  // Throws ApiError on non-2xx because callers discriminate 403 (re-verify)
  // from 409 (phase mismatch — keep polling).
  async getLiveJoinCode(code: string): Promise<{ join_code: string }> {
    const res = await fetch(
      `${getApiUrl()}/api/public/collect/${code}/live-join-code`,
      { method: 'GET', credentials: 'include' },
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: 'Request failed' }));
      throw new ApiError(
        typeof body.detail === 'string' ? body.detail : 'Live join code unavailable',
        res.status,
      );
    }
    return res.json();
  }

  async register(data: {
    username: string;
    email: string;
    password: string;
    confirm_password: string;
    turnstile_token: string;
  }): Promise<{ status: string; message: string }> {
    const response = await fetch(`${getApiUrl()}/api/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Registration failed' }));
      throw new ApiError(error.detail || 'Registration failed', response.status);
    }
    return response.json();
  }

  async getEvents(): Promise<Event[]> {
    return this.transport.fetch('/api/events');
  }

  async createEvent(name: string, expiresHours: number = 6): Promise<Event> {
    return this.transport.fetch('/api/events', {
      method: 'POST',
      body: JSON.stringify({ name, expires_hours: expiresHours }),
    });
  }

  async getEvent(code: string): Promise<Event> {
    return this.transport.fetch(`/api/events/${code}`);
  }

  async updateEvent(
    code: string,
    data: { expires_at?: string; name?: string; frictionless_join?: boolean },
  ): Promise<Event> {
    return this.transport.fetch(`/api/events/${code}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async deleteEvent(code: string): Promise<void> {
    await this.transport.rawFetch(`/api/events/${code}`, { method: 'DELETE' });
  }

  // WrzDJSet set CRUD
}
