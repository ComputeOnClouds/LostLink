import { useState } from 'react';

export function Login({ onLogin }: { onLogin: (email: string, password: string) => Promise<void> }) {
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
        <p style={{ color: 'var(--muted)', marginTop: 0 }}>Access your reports, or your organisation’s inventory.</p>
        <form onSubmit={submit}>
          <label className="field">
            <span>Email</span>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
          </label>
          <label className="field">
            <span>Password</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </label>
          {error && <div className="notice err">{error}</div>}
          <button type="submit" disabled={busy} style={{ width: '100%', marginTop: 4 }}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <div className="seed-hint">
          Demo accounts:<br />
          Individual — <code>user@lostlink.example</code> / <code>User!Pass123</code><br />
          Staff — <code>staff@lostlink.example</code> / <code>Staff!Pass123</code>
        </div>
      </div>
    </div>
  );
}
