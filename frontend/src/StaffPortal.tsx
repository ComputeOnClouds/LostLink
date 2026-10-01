/**
 * Staff portal: review ownership claims against the org, register found items, and
 * manage the org's inventory. Everything is scoped to the staff member's organisation
 * (enforced server-side from the JWT). Rendered when the user is in the Staff group.
 */
import { useEffect, useState } from 'react';
import { ApiClient, FoundItem, StaffClaim } from './api';
import { nowLocal } from './time';
import { itemStatusLabel, claimStateLabel } from './labels';

export function StaffPortal({ api, organisationId }: { api: ApiClient; organisationId: string | null }) {
  const [items, setItems] = useState<FoundItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [msg, setMsg] = useState<string | null>(null);

  async function refresh(q?: string) {
    setLoading(true);
    try {
      const { items } = await api.listItems(q);
      setItems(items);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="grid">
      {!organisationId && (
        <div className="notice err">
          Your staff account isn’t linked to an organisation yet. Email the LostLink admin
          at <strong>satpathy.amrit@u.nus.edu</strong> to register your organisation and
          get it linked to your account.
        </div>
      )}

      <ClaimReview api={api} />

      <div className="card">
        <h2>Register a found item</h2>
        <ItemForm
          onSubmit={async (input) => {
            await api.createItem(input);
            setMsg('Found item registered.');
            await refresh();
          }}
        />
        {msg && <div className="notice ok">{msg}</div>}
      </div>

      <div className="card">
        <h2>Inventory <span style={{ color: 'var(--muted)', fontWeight: 400, fontSize: '.85rem' }}>· {organisationId}</span></h2>
        <div className="search-row">
          <input placeholder="search description…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <button className="secondary" onClick={() => refresh(query.trim() || undefined)}>Search</button>
        </div>
        {loading ? (
          <p className="empty">Loading…</p>
        ) : items.length === 0 ? (
          <p className="empty">No items.</p>
        ) : (
          <ul className="list">
            {items.map((it) => (
              <li key={it.itemId} className="tile">
                <div className="title">{it.description || '(photo-based item)'}</div>
                <div className="meta">
                  {it.locationZone} · {it.eventTime?.slice(0, 10)} ·{' '}
                  <span className={`badge ${it.status}`}>{itemStatusLabel(it.status)}</span>
                </div>
                {it.status !== 'withdrawn' && (
                  <div className="btn-row">
                    <button
                      className="danger sm"
                      onClick={async () => {
                        await api.withdrawItem(it.itemId);
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

function ItemForm({
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
        <span>Photo <span className="hint">(a description can be generated from it)</span></span>
        <input type="file" accept="image/*" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} />
      </label>
      <label className="field">
        <span>Description <span className="hint">(optional if a photo is provided)</span></span>
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="e.g. dark leather wallet, red stripe, found near the entrance" />
      </label>
      <label className="field">
        <span>Location zone*</span>
        <input value={locationZone} onChange={(e) => setLocationZone(e.target.value)} required placeholder="e.g. zone-central-library" />
      </label>
      <label className="field">
        <span>Time found <span className="hint">(defaults to now — change it if you know when)</span></span>
        <input type="datetime-local" value={eventTime} onChange={(e) => setEventTime(e.target.value)} />
      </label>
      {error && <div className="notice err">{error}</div>}
      <button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Register item'}</button>
    </form>
  );
}

/**
 * Claim review: lists claims against this org with the claimant's evidence, and offers
 * only the actions valid from each claim's current state (mirrors the backend claim
 * state machine, so the UI never offers an illegal transition).
 */
function ClaimReview({ api }: { api: ApiClient }) {
  const [claims, setClaims] = useState<StaffClaim[]>([]);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      const { claims } = await api.listOrgClaims();
      setClaims(claims);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function act(
    claimId: string,
    action: 'request-info' | 'approve' | 'reject' | 'reserve' | 'handover'
  ) {
    const needsMsg = action === 'request-info' || action === 'reject';
    const message = needsMsg ? window.prompt('Add a note for the claimant (optional):') || undefined : undefined;
    await api.claimAction(claimId, action, message);
    await refresh();
  }

  // Which staff actions are valid from a given claim state — mirrors backend
  // claim_state.TRANSITIONS so the UI only shows legal moves (terminal states show none).
  const actionsFor = (state: string): Array<'request-info' | 'approve' | 'reject' | 'reserve' | 'handover'> => {
    if (state === 'submitted') return ['request-info', 'approve', 'reject'];
    if (state === 'info_requested') return ['reject'];
    if (state === 'approved') return ['reserve', 'handover'];
    if (state === 'reserved') return ['handover'];
    return [];
  };

  const primary = new Set(['approve', 'reserve', 'handover']);

  return (
    <div className="card">
      <h2>Ownership claims</h2>
      {loading ? (
        <p className="empty">Loading…</p>
      ) : claims.length === 0 ? (
        <p className="empty">No claims yet.</p>
      ) : (
        <ul className="list">
          {claims.map((c) => (
            <li key={c.claimId} className="tile">
              <div>
                <span className={`badge ${c.state}`}>{claimStateLabel(c.state)}</span>{' '}
                <span className="meta">claim {c.claimId.slice(0, 14)}…</span>
              </div>
              <div className="evidence">
                <strong>Evidence:</strong> {c.evidenceText || '(files only)'}
                {c.evidenceKeys.length > 0 && ` · ${c.evidenceKeys.length} file(s)`}
              </div>
              {actionsFor(c.state).length > 0 && (
                <div className="btn-row">
                  {actionsFor(c.state).map((a) => (
                    <button
                      key={a}
                      className={primary.has(a) ? 'sm' : a === 'reject' ? 'danger sm' : 'secondary sm'}
                      onClick={() => act(c.claimId, a)}
                    >
                      {a.replace('-', ' ')}
                    </button>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
