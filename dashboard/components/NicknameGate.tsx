'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { z } from 'zod';
import {
  apiClient,
  ApiError,
  CollectProfileResponse,
  EmailVerificationRequiredError,
  NicknameConflictError,
} from '../lib/api';
import { useGuestIdentity } from '../lib/use-guest-identity';
import { getTurnstileSiteKey, loadTurnstileScript } from '../lib/turnstile';
import { isDevAuthBypassActive } from '../lib/devAuthBypass';
import { ModalOverlay } from './ModalOverlay';
import EmailVerification from './EmailVerification';

const nicknameSchema = z
  .string()
  .trim()
  .min(2, 'Nickname must be at least 2 characters')
  .max(30)
  .regex(/^[a-zA-Z0-9 _.-]+$/, 'Letters, numbers, spaces, . _ - only');

export interface GateResult {
  nickname: string;
  emailVerified: boolean;
  submissionCount: number;
  submissionCap: number;
}

interface Props {
  code: string;
  onComplete: (result: GateResult) => void;
  reverify?: () => Promise<void>;
}

type GateState =
  | 'loading'
  | 'error'
  | 'track_select'
  | 'nickname_input'
  | 'collision_unclaimed'
  | 'collision_claimed'
  | 'email_login'
  | 'email_code'
  | 'email_prompt';

export function NicknameGate({ code, onComplete, reverify }: Props) {
  const identity = useGuestIdentity();

  // DEV-ONLY: skip all gate logic when the dev bypass is active.
  // isDevAuthBypassActive() is inert in production builds by construction.
  useEffect(() => {
    if (!isDevAuthBypassActive()) return;
    onComplete({ nickname: 'dev', emailVerified: false, submissionCount: 0, submissionCap: 0 });
  }, [onComplete]);

  const [gateState, setGateState] = useState<GateState>('loading');
  const [savedNickname, setSavedNickname] = useState('');
  const [nicknameInput, setNicknameInput] = useState('');
  const [emailInput, setEmailInput] = useState('');
  const [codeInput, setCodeInput] = useState('');
  const [collisionNickname, setCollisionNickname] = useState('');
  const [emailVerified, setEmailVerified] = useState(false);
  const [saving, setSaving] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
  const [verifyingCode, setVerifyingCode] = useState(false);
  const [inputError, setInputError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);
  const [profileCache, setProfileCache] = useState<CollectProfileResponse | null>(null);
  // A name the guest chose that requires email verification before it can be
  // claimed. Stashed when the save is blocked, then auto-applied after verify.
  const [pendingNickname, setPendingNickname] = useState<string | null>(null);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [otpTurnstileToken, setOtpTurnstileToken] = useState<string>('');
  const otpWidgetRef = useRef<HTMLDivElement | null>(null);
  const otpWidgetIdRef = useRef<string | null>(null);

  useEffect(() => {
    return () => {
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (gateState !== 'email_login') return;
    if (!otpWidgetRef.current) return;
    let cancelled = false;
    void (async () => {
      const sitekey = await getTurnstileSiteKey();
      if (!sitekey || cancelled) {
        setOtpTurnstileToken('dev-bypass');
        return;
      }
      await loadTurnstileScript();
      if (cancelled || !window.turnstile || !otpWidgetRef.current) return;
      otpWidgetIdRef.current = window.turnstile.render(otpWidgetRef.current, {
        sitekey,
        appearance: 'interaction-only',
        size: 'normal',
        callback: (token: string) => setOtpTurnstileToken(token),
        'error-callback': () => setOtpTurnstileToken(''),
        'expired-callback': () => setOtpTurnstileToken(''),
      });
    })();
    return () => {
      cancelled = true;
      if (otpWidgetIdRef.current && window.turnstile) {
        window.turnstile.remove(otpWidgetIdRef.current);
        otpWidgetIdRef.current = null;
      }
      setOtpTurnstileToken('');
    };
  }, [gateState]);

  const loadProfile = useCallback(async () => {
    setGateState('loading');
    try {
      const p = await apiClient.getCollectProfile(code);
      setProfileCache(p);
      if (p.nickname && p.email_verified) {
        onComplete({
          nickname: p.nickname,
          emailVerified: true,
          submissionCount: p.submission_count,
          submissionCap: p.submission_cap,
        });
      } else if (p.nickname) {
        setSavedNickname(p.nickname);
        setGateState('email_prompt');
      } else {
        setGateState('track_select');
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        onComplete({ nickname: '', emailVerified: false, submissionCount: 0, submissionCap: 0 });
      } else {
        setGateState('error');
      }
    }
  }, [code, onComplete]);

  // Wait for the identify endpoint to set the wrzdj_guest cookie before we
  // call getCollectProfile. Otherwise the backend can't resolve guest_id and
  // (with IP fallback gone) returns the empty default — a returning guest
  // would briefly see the nickname-input modal before settling.
  useEffect(() => {
    if (identity.isLoading) return;
    if (isDevAuthBypassActive()) return; // bypass effect handles onComplete directly
    loadProfile();
  }, [loadProfile, identity.isLoading]);

  const handleSaveNickname = async () => {
    const parsed = nicknameSchema.safeParse(nicknameInput);
    if (!parsed.success) {
      setInputError(parsed.error.issues[0].message);
      return;
    }
    setSaving(true);
    setInputError(null);
    try {
      const p = await apiClient.setCollectProfile(code, { nickname: parsed.data }, reverify);
      setProfileCache(p);
      setSavedNickname(parsed.data);
      setSavedFlash(true);
      flashTimerRef.current = setTimeout(() => {
        setSavedFlash(false);
        if (emailVerified) {
          onComplete({
            nickname: parsed.data,
            emailVerified: true,
            submissionCount: p.submission_count,
            submissionCap: p.submission_cap,
          });
        } else {
          setGateState('email_prompt');
        }
      }, 1500);
    } catch (err) {
      if (err instanceof NicknameConflictError) {
        setCollisionNickname(parsed.data);
        setGateState(err.claimed ? 'collision_claimed' : 'collision_unclaimed');
      } else if (err instanceof EmailVerificationRequiredError) {
        // Claiming a name requires a verified email (collect hardening, #324).
        // Stash the chosen name and route into the email flow rather than
        // showing a dead-end error; the name is claimed after verification.
        setPendingNickname(parsed.data);
        setSavedNickname(parsed.data);
        setGateState('email_login');
      } else {
        setInputError(err instanceof ApiError ? err.message : "Couldn't save — please try again");
      }
    } finally {
      setSaving(false);
    }
  };

  const handleSendCode = async () => {
    if (!otpTurnstileToken) {
      setInputError('Please complete the human-verification check.');
      return;
    }
    setSendingCode(true);
    setInputError(null);
    try {
      await apiClient.requestVerificationCode(emailInput, otpTurnstileToken);
      // Reset widget for next attempt (fresh token per send)
      if (otpWidgetIdRef.current && window.turnstile) {
        window.turnstile.reset(otpWidgetIdRef.current);
      }
      setOtpTurnstileToken('');
      setGateState('email_code');
    } catch (err) {
      setInputError(err instanceof ApiError ? err.message : 'Failed to send code. Try again.');
    } finally {
      setSendingCode(false);
    }
  };

  const handleConfirmCode = async () => {
    setVerifyingCode(true);
    setInputError(null);
    // Tracks whether the OTP itself succeeded, so a later (deferred-claim)
    // failure is not misreported as a bad code.
    let verified = false;
    try {
      await apiClient.confirmVerificationCode(emailInput, codeInput);
      const p = await apiClient.getCollectProfile(code);
      setProfileCache(p);
      setEmailVerified(true);
      verified = true;
      if (p.nickname) {
        onComplete({
          nickname: p.nickname,
          emailVerified: true,
          submissionCount: p.submission_count,
          submissionCap: p.submission_cap,
        });
        return;
      }
      if (!pendingNickname) {
        setGateState('nickname_input');
        return;
      }
      // Email is verified — claim the deferred name as a separate step so a
      // claim failure can't strand the guest behind an already-consumed code.
      const claimed = await apiClient.setCollectProfile(
        code,
        { nickname: pendingNickname },
        reverify,
      );
      setPendingNickname(null);
      onComplete({
        nickname: claimed.nickname ?? pendingNickname,
        emailVerified: true,
        submissionCount: claimed.submission_count,
        submissionCap: claimed.submission_cap,
      });
    } catch (err) {
      if (err instanceof NicknameConflictError) {
        // The deferred name was claimed by someone else during verification.
        setCollisionNickname(pendingNickname ?? '');
        setPendingNickname(null);
        setGateState(err.claimed ? 'collision_claimed' : 'collision_unclaimed');
      } else if (verified) {
        // OTP succeeded but the deferred claim failed — keep the verified state
        // and move off the consumed-code screen so the guest can retry the name.
        setPendingNickname(null);
        setInputError(
          err instanceof ApiError ? err.message : "Couldn't save nickname — please try again",
        );
        setGateState('nickname_input');
      } else {
        setInputError(err instanceof ApiError ? err.message : 'Invalid or expired code.');
      }
    } finally {
      setVerifyingCode(false);
    }
  };

  const handleSkip = () => {
    onComplete({
      nickname: savedNickname,
      emailVerified: false,
      submissionCount: profileCache?.submission_count ?? 0,
      submissionCap: profileCache?.submission_cap ?? 0,
    });
  };

  const handleVerified = () => {
    onComplete({
      nickname: savedNickname,
      emailVerified: true,
      submissionCount: profileCache?.submission_count ?? 0,
      submissionCap: profileCache?.submission_cap ?? 0,
    });
  };

  // ── loading ───────────────────────────────────────────────────────────────

  if (gateState === 'loading') {
    return (
      <ModalOverlay card>
        <div style={{ textAlign: 'center', padding: '1rem' }}>
          <p style={{ color: 'var(--text-secondary)' }}>Connecting…</p>
        </div>
      </ModalOverlay>
    );
  }

  if (gateState === 'error') {
    return (
      <ModalOverlay card>
        <p style={{ marginBottom: '1rem' }}>
          Couldn&apos;t connect to the event. Check your connection and try again.
        </p>
        <button className="btn btn-primary" style={{ width: '100%' }} onClick={loadProfile}>
          Retry
        </button>
      </ModalOverlay>
    );
  }

  // ── track_select ──────────────────────────────────────────────────────────

  if (gateState === 'track_select') {
    return (
      <ModalOverlay card>
        <h2 style={{ marginBottom: '0.5rem' }}>Join the event</h2>
        <p style={{ color: 'var(--text-secondary)', marginBottom: '1.25rem', fontSize: '0.9rem' }}>
          How would you like to identify yourself?
        </p>
        <button
          className="btn btn-primary"
          style={{ width: '100%', marginBottom: '0.75rem' }}
          onClick={() => setGateState('nickname_input')}
        >
          New name
        </button>
        <button
          className="btn btn-secondary"
          style={{ width: '100%' }}
          onClick={() => setGateState('email_login')}
        >
          Have email / log in
        </button>
      </ModalOverlay>
    );
  }

  // ── nickname_input ────────────────────────────────────────────────────────

  if (gateState === 'nickname_input') {
    return (
      <ModalOverlay card>
        <h2 style={{ marginBottom: '0.75rem' }}>What&apos;s your nickname?</h2>
        <div className="form-group">
          <input
            type="text"
            className="input"
            placeholder="DancingQueen"
            value={nicknameInput}
            onChange={(e) => {
              setNicknameInput(e.target.value);
              setInputError(null);
            }}
            maxLength={30}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && nicknameInput.trim()) handleSaveNickname();
            }}
            autoFocus
          />
        </div>
        {inputError && <p className="collection-fieldset-error">{inputError}</p>}
        {savedFlash && (
          <p style={{ color: '#22c55e', marginBottom: '0.5rem' }}>&#10003; Nickname saved!</p>
        )}
        <button
          className="btn btn-primary"
          style={{ width: '100%' }}
          disabled={!nicknameInput.trim() || saving}
          onClick={handleSaveNickname}
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </ModalOverlay>
    );
  }

  // ── collision_unclaimed ───────────────────────────────────────────────────

  if (gateState === 'collision_unclaimed') {
    return (
      <ModalOverlay card>
        <h2 style={{ marginBottom: '0.75rem' }}>Nickname taken</h2>
        <p style={{ color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
          <strong>&ldquo;{collisionNickname}&rdquo;</strong> is already taken.
        </p>
        <p
          style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--border)',
            borderRadius: '8px',
            padding: '0.75rem',
            fontSize: '0.875rem',
            color: 'var(--text-secondary)',
            marginBottom: '1rem',
          }}
        >
          Not claimed yet. If this is yours, go back to the original device you used and claim it
          there with your email.
        </p>
        <button
          className="btn btn-secondary"
          style={{ width: '100%' }}
          onClick={() => {
            setNicknameInput('');
            setGateState('nickname_input');
          }}
        >
          Try a different nickname
        </button>
      </ModalOverlay>
    );
  }

  // ── collision_claimed ─────────────────────────────────────────────────────

  if (gateState === 'collision_claimed') {
    return (
      <ModalOverlay card>
        <h2 style={{ marginBottom: '0.75rem' }}>Nickname taken</h2>
        <p style={{ color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
          <strong>&ldquo;{collisionNickname}&rdquo;</strong> is already taken.
        </p>
        <p
          style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--border)',
            borderRadius: '8px',
            padding: '0.75rem',
            fontSize: '0.875rem',
            color: 'var(--text-secondary)',
            marginBottom: '1rem',
          }}
        >
          This nickname has an email attached — if it&apos;s yours, log in to reclaim it.
        </p>
        <button
          className="btn btn-primary"
          style={{ width: '100%', marginBottom: '0.75rem' }}
          onClick={() => setGateState('email_login')}
        >
          Log in with email
        </button>
        <button
          className="btn btn-secondary"
          style={{ width: '100%' }}
          onClick={() => {
            setNicknameInput('');
            setGateState('nickname_input');
          }}
        >
          Try a different nickname
        </button>
      </ModalOverlay>
    );
  }

  // ── email_login ───────────────────────────────────────────────────────────

  if (gateState === 'email_login') {
    return (
      <ModalOverlay card>
        <h2 style={{ marginBottom: '0.5rem' }}>Log in with email</h2>
        <p style={{ color: 'var(--text-secondary)', marginBottom: '1rem', fontSize: '0.9rem' }}>
          Enter your email to receive a login code.
        </p>
        <div className="form-group">
          <input
            type="email"
            className="input"
            placeholder="you@example.com"
            value={emailInput}
            onChange={(e) => {
              setEmailInput(e.target.value);
              setInputError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && emailInput.trim()) handleSendCode();
            }}
            autoFocus
          />
        </div>
        <div ref={otpWidgetRef} style={{ margin: '1rem 0' }} />
        {inputError && <p className="collection-fieldset-error">{inputError}</p>}
        <button
          className="btn btn-primary"
          style={{ width: '100%', marginBottom: '0.75rem' }}
          disabled={!emailInput.trim() || sendingCode || !otpTurnstileToken}
          onClick={handleSendCode}
        >
          {sendingCode ? 'Sending…' : 'Send code'}
        </button>
        <button
          className="btn btn-secondary"
          style={{ width: '100%' }}
          onClick={() => {
            // Abandon any deferred name claim so it isn't auto-applied if the
            // guest later verifies via the normal email-login path.
            setPendingNickname(null);
            setSavedNickname('');
            setGateState('track_select');
          }}
        >
          ← Back
        </button>
      </ModalOverlay>
    );
  }

  // ── email_code ────────────────────────────────────────────────────────────

  if (gateState === 'email_code') {
    return (
      <ModalOverlay card>
        <h2 style={{ marginBottom: '0.5rem' }}>Check your email</h2>
        <p style={{ color: 'var(--text-secondary)', marginBottom: '1rem', fontSize: '0.9rem' }}>
          Enter the 6-digit code sent to {emailInput}.
        </p>
        <div className="form-group">
          <input
            type="text"
            className="input"
            placeholder="6-digit code"
            value={codeInput}
            onChange={(e) => {
              setCodeInput(e.target.value.replace(/\D/g, '').slice(0, 6));
              setInputError(null);
            }}
            maxLength={6}
            autoFocus
          />
        </div>
        {inputError && <p className="collection-fieldset-error">{inputError}</p>}
        <button
          className="btn btn-primary"
          style={{ width: '100%', marginBottom: '0.75rem' }}
          disabled={codeInput.length !== 6 || verifyingCode}
          onClick={handleConfirmCode}
        >
          {verifyingCode ? 'Verifying…' : 'Verify'}
        </button>
        <button
          className="btn btn-secondary"
          style={{ width: '100%' }}
          onClick={() => {
            setCodeInput('');
            setGateState('email_login');
          }}
        >
          Resend code
        </button>
      </ModalOverlay>
    );
  }

  // ── email_prompt ──────────────────────────────────────────────────────────

  return (
    <ModalOverlay card>
      <h2 style={{ marginBottom: '0.5rem' }}>Hi, {savedNickname}! 👋</h2>
      <p style={{ color: 'var(--text-secondary)', marginBottom: '1rem', fontSize: '0.9rem' }}>
        Add your email to unlock cross-device access and leaderboards.
      </p>
      <EmailVerification isVerified={false} onVerified={handleVerified} onSkip={handleSkip} />
    </ModalOverlay>
  );
}
