/**
 * LostLink frontend root: loads runtime config, manages auth state, and routes to the
 * Individual or Staff portal based on the caller's Cognito group. Pragmatic by design
 * (RATIONALE ADR-008) — the clean seam is the ApiClient in api.ts.
 */
import { useEffect, useState } from 'react';
import { loadConfig, RuntimeConfig } from './config';
import { Identity, currentIdentity, signIn, signOut } from './auth';
import { ApiClient } from './api';
import { Login } from './Login';
import { Register } from './Register';
import { Recover } from './Recover';
import { IndividualPortal } from './IndividualPortal';
import { StaffPortal } from './StaffPortal';

export function App() {
  const [cfg, setCfg] = useState<RuntimeConfig | null>(null);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [authScreen, setAuthScreen] = useState<'login' | 'register' | 'recover'>('login');
  const [authNotice, setAuthNotice] = useState<string | null>(null);

  useEffect(() => {
    loadConfig()
      .then(async (c) => {
        setCfg(c);
        setIdentity(await currentIdentity(c));
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  async function handleLogin(email: string, password: string) {
    if (!cfg) return;
    const id = await signIn(cfg, email, password);
    setIdentity(id);
  }

  // After a successful registration + confirmation, sign the new user straight in.
  async function handleRegistered(email: string, password: string) {
    await handleLogin(email, password);
    setAuthScreen('login');
  }

  function handleLogout() {
    if (cfg) signOut(cfg);
    setIdentity(null);
  }

  if (loading) return <Centered>Loading…</Centered>;
  if (error) return <Centered>Configuration error: {error}</Centered>;
  if (!cfg) return <Centered>No configuration.</Centered>;

  if (!identity) {
    return (
      <Shell>
        {authScreen === 'register' ? (
          <Register
            cfg={cfg}
            onConfirmed={handleRegistered}
            onBackToLogin={() => setAuthScreen('login')}
          />
        ) : authScreen === 'recover' ? (
          <Recover
            cfg={cfg}
            onBack={() => setAuthScreen('login')}
            onComplete={() => {
              setAuthNotice('Your password has been reset. Sign in with your new password.');
              setAuthScreen('login');
            }}
          />
        ) : (
          <Login
            onLogin={handleLogin}
            onRegister={() => setAuthScreen('register')}
            onForgot={() => setAuthScreen('recover')}
            notice={authNotice}
          />
        )}
      </Shell>
    );
  }

  const api = new ApiClient(cfg, identity.idToken);
  const isStaff = identity.groups.includes('Staff');

  return (
    <>
      <TopBar
        email={identity.email}
        roleLabel={isStaff ? `Staff · ${identity.organisationId ?? 'no org'}` : 'Individual'}
        onLogout={handleLogout}
      />
      <div className="page">
        <div className="hero">
          <h1>{isStaff ? 'Organisation workspace' : 'Your lost & found'}</h1>
          <p>
            {isStaff
              ? 'Register found items and review ownership claims for your organisation.'
              : 'Report a lost item once — we search partner organisations for you.'}
          </p>
        </div>
        {isStaff ? (
          <StaffPortal api={api} organisationId={identity.organisationId} />
        ) : (
          <IndividualPortal api={api} />
        )}
      </div>
    </>
  );
}

function TopBar({ email, roleLabel, onLogout }: { email: string | null; roleLabel: string; onLogout: () => void }) {
  return (
    <div className="topbar">
      <div className="brand">
        <span className="logo">◎</span>
        <span>LostLink</span>
        <span className="tag">· cross-organisation lost &amp; found</span>
      </div>
      <div className="userbox">
        <span className="role-badge">{roleLabel}</span>
        <span>{email}</span>
        <button className="secondary sm" onClick={onLogout}>Sign out</button>
      </div>
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <>
      <div className="topbar">
        <div className="brand">
          <span className="logo">◎</span>
          <span>LostLink</span>
          <span className="tag">· cross-organisation lost &amp; found</span>
        </div>
      </div>
      {children}
    </>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="center-screen">{children}</div>;
}
