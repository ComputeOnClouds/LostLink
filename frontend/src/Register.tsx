/**
 * Self-service registration for individuals who have lost something.
 *
 * Two steps: (1) email + password -> Cognito SignUp emails a verification code;
 * (2) enter the code -> confirm. On success we hand the credentials back to App so it
 * can sign the user straight in. New users become Individuals via the pool's
 * post-confirmation trigger (see auth-stack.ts) — no role is chosen here.
 */
import { useState } from 'react';
import { RuntimeConfig } from './config';
import { signUp, confirmSignUp, resendCode } from './auth';

type Step = 'details' | 'confirm';

export function Register({
  cfg,
  onConfirmed,
  onBackToLogin,
}: {
  cfg: RuntimeConfig;
  onConfirmed: (email: string, password: string) => Promise<void>;
  onBackToLogin: () => void;
}) {
  const [step, setStep] = useState<Step>('details');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const passwordOk = password.length >= 8 && /[a-z]/.test(password) && /[A-Z]/.test(password) && /\d/.test(password);

  async function submitDetails(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }
    if (!passwordOk) {
      setError('Password needs 8+ characters with upper, lower and a number.');
      return;
    }
    setBusy(true);
    try {
      const needsCode = await signUp(cfg, email.trim(), password);
      if (needsCode) {
        setInfo(`We emailed a verification code to ${email.trim()}.`);
        setStep('confirm');
      } else {
        // Pool auto-confirmed (not our config, but handle it): sign straight in.
        await onConfirmed(email.trim(), password);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-up failed');
    } finally {
      setBusy(false);
    }
  }

  async function submitCode(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await confirmSignUp(cfg, email.trim(), code);
      // Confirmed -> post-confirmation trigger adds the Individual group -> sign in.
      await onConfirmed(email.trim(), password);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Confirmation failed');
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setError(null);
    setInfo(null);
    try {
      await resendCode(cfg, email.trim());
      setInfo('A new code is on its way.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not resend code');
    }
  }

  return (
    <div className="login-wrap">
      <div className="card">
        <h2>{step === 'details' ? 'Create your account' : 'Confirm your email'}</h2>

        {step === 'details' ? (
          <>
            <p style={{ color: 'var(--muted)', marginTop: 0 }}>
              Report a lost item once — we search partner organisations for you.
            </p>
            {error && <div className="notice err">{error}</div>}
            <form onSubmit={submitDetails}>
              <label className="field">
                <span>Email</span>
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
              </label>
              <label className="field">
                <span>Password</span>
                <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
              </label>
              <label className="field">
                <span>Confirm password</span>
                <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
              </label>
              <p className="hint">At least 8 characters, with an uppercase letter, a lowercase letter and a number.</p>
              <button type="submit" disabled={busy} style={{ width: '100%', marginTop: 4 }}>
                {busy ? 'Creating…' : 'Create account'}
              </button>
            </form>
          </>
        ) : (
          <>
            {info && <div className="notice ok">{info}</div>}
            {error && <div className="notice err">{error}</div>}
            <form onSubmit={submitCode}>
              <label className="field">
                <span>Verification code</span>
                <input
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  required
                  autoFocus
                />
              </label>
              <button type="submit" disabled={busy} style={{ width: '100%', marginTop: 4 }}>
                {busy ? 'Confirming…' : 'Confirm & sign in'}
              </button>
            </form>
            <p className="auth-switch">
              Didn’t get it?{' '}
              <button type="button" className="linklike" onClick={resend}>
                Resend code
              </button>
            </p>
          </>
        )}

        <p className="auth-switch">
          Already have an account?{' '}
          <button type="button" className="linklike" onClick={onBackToLogin}>
            Sign in
          </button>
        </p>
      </div>
    </div>
  );
}
