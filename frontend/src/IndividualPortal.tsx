/**
 * Individual portal: report a lost item, see potential cross-org matches (details
 * hidden), submit/track ownership claims, and manage one's own reports. Rendered when
 * the signed-in user is NOT in the Staff group (see App.tsx role gate).
 */
import { useEffect, useState } from 'react';
import { ApiClient, Report, MatchSuggestion, Claim } from './api';
import { nowLocal } from './time';
import { reportStatusLabel, claimStateLabel } from './labels';

export function IndividualPortal({ api }: { api: ApiClient }) {
  const [reports, setReports] = useState<Report[]>([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      const { reports } = await api.listReports();
      setReports(reports);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="grid">
      <div className="card">
        <h2>Report a lost item</h2>
        <ReportForm
          onSubmit={async (input) => {
            await api.createReport(input);
            setMsg('Report submitted. We’ll notify you if a partner organisation may have it.');
            await refresh();
          }}
        />
        {msg && <div className="notice ok">{msg}</div>}
      </div>

      <MatchesAndClaims api={api} />

      <div className="card">
        <h2>My reports</h2>
        {loading ? (
          <p className="empty">Loading…</p>
        ) : reports.length === 0 ? (
          <p className="empty">No reports yet.</p>
        ) : (
          <ul className="list">
            {reports.map((r) => (
              <li key={r.itemId} className="tile">
                <div className="title">{r.description || '(photo-based report)'}</div>
                <div className="meta">
                  {r.locationZone} · {r.eventTime?.slice(0, 10)} ·{' '}
                  <span className={`badge ${r.status}`}>{reportStatusLabel(r.status)}</span>
                </div>
                {r.status !== 'withdrawn' && (
                  <div className="btn-row">
                    <button
                      className="danger sm"
                      onClick={async () => {
                        await api.withdrawReport(r.itemId);
                        await refresh();
                      }}
                    >
                      Withdraw
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function ReportForm({
  onSubmit,
}: {
  onSubmit: (input: { description?: string; locationZone: string; eventTime?: string; photo?: File | null }) => Promise<void>;
}) {
  const [description, setDescription] = useState('');
  const [locationZone, setLocationZone] = useState('');
  // Prefill with the current local time; this exact value is submitted if left unchanged.
  const [eventTime, setEventTime] = useState(nowLocal());
  const [photo, setPhoto] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSubmit({
        description: description.trim() || undefined,
        locationZone: locationZone.trim(),
        eventTime: eventTime ? new Date(eventTime).toISOString() : undefined,
        photo,
      });
      setDescription('');
      setLocationZone('');
      setEventTime(nowLocal());
      setPhoto(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Submit failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <label className="field">
        <span>Description <span className="hint">(optional if you add a photo)</span></span>
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="e.g. black leather wallet with a red stripe" />
      </label>
      <label className="field">
        <span>Location zone*</span>
        <input value={locationZone} onChange={(e) => setLocationZone(e.target.value)} required placeholder="e.g. zone-central-library" />
      </label>
      <label className="field">
        <span>Approx. time lost <span className="hint">(defaults to now — change it if you know when)</span></span>
        <input type="datetime-local" value={eventTime} onChange={(e) => setEventTime(e.target.value)} />
      </label>
      <label className="field">
        <span>Photo <span className="hint">(optional)</span></span>
        <input type="file" accept="image/*" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
      </label>
      {error && <div className="notice err">{error}</div>}
      <button type="submit" disabled={busy}>{busy ? 'Submitting…' : 'Submit report'}</button>
    </form>
  );
}

/**
 * Shows the individual's potential matches (with a confidence bar, no item details) and
 * their claims. Submitting a claim collects ownership evidence via a prompt; the found
 * item's details only appear on a claim once staff have approved it.
 */
function MatchesAndClaims({ api }: { api: ApiClient }) {
  const [matches, setMatches] = useState<MatchSuggestion[]>([]);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [loading, setLoading] = useState(true);
  const [note, setNote] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      const [m, c] = await Promise.all([api.listMatches(), api.listClaims()]);
      setMatches(m.matches);
      setClaims(c.claims);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function claim(s: MatchSuggestion) {
    const evidence = window.prompt(
      'Describe proof of ownership (e.g. distinguishing marks, receipt details):'
    );
    if (!evidence) return;
    await api.submitClaim({
      queryItemId: s.queryItemId,
      candidateItemId: s.candidateItemId,
      evidenceText: evidence,
    });
    setNote('Claim submitted. The organisation will review your evidence.');
    await refresh();
  }

  return (
    <div className="card">
      <h2>Potential matches</h2>
      {loading ? (
        <p className="empty">Loading…</p>
      ) : matches.length === 0 ? (
        <p className="empty">No potential matches yet. We’ll notify you if one appears.</p>
      ) : (
        <ul className="list">
          {matches.map((s) => (
            <li key={`${s.queryItemId}:${s.candidateItemId}`} className="tile">
              <div className="title">{s.message}</div>
              <div className="meta">held by <strong>{s.organisationId}</strong></div>
              <div className="confidence">
                <div className="bar"><span style={{ width: `${Math.round(s.score * 100)}%` }} /></div>
                <span className="pct">{Math.round(s.score * 100)}% match</span>
              </div>
              <div className="btn-row">
                <button className="sm" onClick={() => claim(s)}>This is mine — submit a claim</button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {note && <div className="notice ok">{note}</div>}

      <hr className="divider" />
      <h3>My claims</h3>
      {claims.length === 0 ? (
        <p className="empty">No claims yet.</p>
      ) : (
        <ul className="list">
          {claims.map((c) => (
            <li key={c.claimId} className="tile">
              <div>
                Claim to <strong>{c.organisationId}</strong> ·{' '}
                <span className={`badge ${c.state}`}>{claimStateLabel(c.state)}</span>
              </div>
              {c.item ? (
                <div className="evidence">
                  <strong>Verified item:</strong> {c.item.description} ({c.item.locationZone}). {c.collection}
                </div>
              ) : (
                <div className="hidden-note">Item details stay hidden until the organisation approves your claim.</div>
              )}
              {['submitted', 'info_requested'].includes(c.state) && (
                <div className="btn-row">
                  <button
                    className="danger sm"
                    onClick={async () => {
                      await api.cancelClaim(c.claimId);
                      await refresh();
                    }}
                  >
                    Cancel claim
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
