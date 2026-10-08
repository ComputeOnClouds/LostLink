import { useState } from 'react';

export function Login({
  onLogin,
  onRegister,
  onForgot,
  notice,
}: {
  onLogin: (email: string, password: string) => Promise<void>;
  onRegister: () => void;
  onForgot: () => void;
  notice?: string | null;
}) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onLogin(email.trim(), password);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <div className="card">
        <h2>Sign in</h2>
        <p className="auth-intro">Access your reports, or your organisation’s inventory.</p>
        {notice && <div className="notice ok" role="status">{notice}</div>}
        <form onSubmit={submit}>
          <label className="field">
            <span>Email</span>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
          </label>
          <div className="field">
            <div className="label-row">
              <label htmlFor="login-password">Password</label>
              <button type="button" className="linklike" onClick={onForgot}>Forgot password?</button>
            </div>
            <input id="login-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {error && <div className="notice err" role="alert">{error}</div>}
          <button type="submit" disabled={busy} className="full-button">
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <p className="auth-switch">
          Lost something and new here?{' '}
          <button type="button" className="linklike" onClick={onRegister}>
            Create an account
          </button>
        </p>
        <div className="seed-hint">
          Demo accounts:<br />
          Individual — <code>user@lostlink.example</code> / <code>User!Pass123</code><br />
          Staff — <code>staff@lostlink.example</code> / <code>Staff!Pass123</code>
          <br /><br />
          Staff accounts for an organisation are provisioned by the LostLink admin
          at <code>satpathy.amrit@u.nus.edu</code>.
        </div>
      </div>
    </div>
  );
}
