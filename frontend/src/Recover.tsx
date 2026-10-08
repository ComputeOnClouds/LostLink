import { useState } from 'react';
import { RuntimeConfig } from './config';
import { confirmPasswordReset, requestPasswordReset } from './auth';

export function Recover({
  cfg,
  onComplete,
  onBack,
}: {
  cfg: RuntimeConfig;
  onComplete: () => void;
  onBack: () => void;
}) {
  const [step, setStep] = useState<'email' | 'confirm'>('email');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const passwordOk = password.length >= 8 && /[a-z]/.test(password) && /[A-Z]/.test(password) && /\d/.test(password);

  async function requestCode(event?: React.FormEvent) {
    event?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await requestPasswordReset(cfg, email.trim());
      setInfo('If an eligible account exists, a reset code has been sent to that email address.');
      setStep('confirm');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not request a reset code. Try again shortly.');
    } finally { setBusy(false); }
  }

  async function reset(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (password !== confirm) { setError('Passwords do not match.'); return; }
    if (!passwordOk) { setError('Use at least 8 characters with uppercase, lowercase and a number.'); return; }
    setBusy(true);
    try {
      await confirmPasswordReset(cfg, email.trim(), code, password);
      onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The code or new password could not be accepted.');
    } finally { setBusy(false); }
  }

  return (
    <div className="login-wrap">
      <div className="card">
        <h2>{step === 'email' ? 'Reset your password' : 'Enter your reset code'}</h2>
        {step === 'email' ? (
          <form onSubmit={requestCode}>
            <p className="form-intro">We’ll send recovery instructions to the email on your account.</p>
            <label className="field"><span>Email</span><input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required autoFocus /></label>
            {error && <div className="notice err" role="alert">{error}</div>}
            <button className="full-button" disabled={busy}>{busy ? 'Requesting…' : 'Send reset code'}</button>
          </form>
        ) : (
          <form onSubmit={reset}>
            {info && <div className="notice info" role="status">{info}</div>}
            <label className="field"><span>Reset code</span><input value={code} onChange={(event) => setCode(event.target.value)} autoComplete="one-time-code" inputMode="numeric" required autoFocus /></label>
            <label className="field"><span>New password</span><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="new-password" required /></label>
            <label className="field"><span>Confirm new password</span><input type="password" value={confirm} onChange={(event) => setConfirm(event.target.value)} autoComplete="new-password" required /></label>
            <p className="hint">At least 8 characters, with an uppercase letter, a lowercase letter and a number.</p>
            {error && <div className="notice err" role="alert">{error}</div>}
            <button className="full-button" disabled={busy}>{busy ? 'Resetting…' : 'Set new password'}</button>
            <div className="auth-actions">
              <button type="button" className="linklike" disabled={busy} onClick={() => void requestCode()}>Resend code</button>
              <button type="button" className="linklike" onClick={() => { setStep('email'); setCode(''); setError(null); }}>Change email</button>
            </div>
          </form>
        )}
        <p className="auth-switch"><button type="button" className="linklike" onClick={onBack}>Back to sign in</button></p>
      </div>
    </div>
  );
}
