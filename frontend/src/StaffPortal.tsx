import { useEffect, useState } from 'react';
import { ApiClient, FoundItem, StaffClaim } from './api';
import { ClaimDetailPanel } from './ClaimWorkflow';
import { DescriptionBlock } from './DescriptionDisclosure';
import { ItemEditor } from './ItemEditor';
import { claimStateLabel, itemStatusLabel } from './labels';
import { formatLocalTime } from './time';

export function StaffPortal({ api, organisationId }: { api: ApiClient; organisationId: string | null }) {
  const [items, setItems] = useState<FoundItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [editing, setEditing] = useState<FoundItem | null>(null);

  async function refresh(search?: string) {
    setLoading(true);
    try { setItems((await api.listItems(search)).items); }
    finally { setLoading(false); }
  }

  useEffect(() => { void refresh(); }, []);

  return (
    <div className="grid portal-grid">
      {!organisationId && (
        <div className="notice err">Your staff account isn’t linked to an organisation. Contact the LostLink administrator.</div>
      )}

      <ClaimReview api={api} />

      <section className="card">
        <h2>Register a found item</h2>
        <ItemEditor
          api={api}
          kind="item"
          submitLabel="Register item"
          onSave={async (input) => {
            await api.createItem(input);
            setMessage('Found item registered. Matching will continue in the background.');
            await refresh();
          }}
        />
        {message && <div className="notice ok" role="status">{message}</div>}
      </section>

      <section className="card">
        <div className="section-heading">
          <div><h2>Inventory</h2><p className="meta">{organisationId}</p></div>
        </div>
        <form className="search-row" onSubmit={(event) => { event.preventDefault(); void refresh(query.trim() || undefined); }}>
          <label className="sr-only" htmlFor="inventory-search">Search inventory</label>
          <input id="inventory-search" placeholder="Search description…" value={query} onChange={(event) => setQuery(event.target.value)} />
          <button>Search</button>
          {query && <button type="button" className="secondary" onClick={() => { setQuery(''); void refresh(); }}>Clear</button>}
        </form>
        {loading ? <p className="empty">Loading inventory…</p> : items.length === 0 ? (
          <p className="empty">No items match this view.</p>
        ) : (
          <ul className="list">
            {items.map((item) => (
              <li key={item.itemId} className="tile">
                {editing?.itemId === item.itemId ? (
                  <ItemEditor
                    api={api}
                    kind="item"
                    initial={editing}
                    submitLabel="Save changes"
                    onCancel={() => setEditing(null)}
                    onSave={async (input) => {
                      const saved = await api.updateItem(item.itemId, input);
                      setMessage(saved.rematching ? 'Item saved. We’re checking matches again.' : 'Item saved.');
                      setEditing(null);
                      await refresh(query.trim() || undefined);
                    }}
                  />
                ) : (
                  <>
                    <div className="tile-heading">
                      <DescriptionBlock description={item.description} />
                      <span className={`badge ${item.status}`}>{itemStatusLabel(item.status)}</span>
                    </div>
                    <div className="meta">{item.location?.name || item.locationZone} · {formatLocalTime(item.eventTime)}</div>
                    <div className="btn-row">
                      {item.status === 'available' && (
                        <button type="button" className="secondary sm" onClick={async () => setEditing(await api.getItem(item.itemId))}>Edit</button>
                      )}
                      {item.status === 'available' && (
                        <button type="button" className="danger sm" onClick={async () => { await api.withdrawItem(item.itemId); await refresh(); }}>Withdraw</button>
                      )}
                    </div>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function ClaimReview({ api }: { api: ApiClient }) {
  const [claims, setClaims] = useState<StaffClaim[]>([]);
  const [loading, setLoading] = useState(true);
  const [openClaim, setOpenClaim] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try { setClaims((await api.listOrgClaims()).claims); }
    finally { setLoading(false); }
  }

  useEffect(() => { void refresh(); }, []);

  return (
    <section className="card">
      <div className="section-heading">
        <h2>Ownership claims</h2>
        <button className="secondary sm" onClick={() => void refresh()}>Refresh</button>
      </div>
      {loading ? <p className="empty">Loading claims…</p> : claims.length === 0 ? (
        <p className="empty">No claims yet. New ownership claims will appear here.</p>
      ) : (
        <ul className="list">
          {claims.map((claim) => (
            <li key={claim.claimId} className="tile">
              <div className="tile-heading">
                <span className={`badge ${claim.state}`}>{claimStateLabel(claim.state)}</span>
                <span className="meta">Updated {formatLocalTime(claim.updatedAt)}</span>
              </div>
              <div className="evidence"><strong>Evidence:</strong> {claim.evidenceText || '(files only)'}</div>
              <div className="btn-row"><button className="secondary sm" onClick={() => setOpenClaim(claim.claimId)}>View claim</button></div>
            </li>
          ))}
        </ul>
      )}
      {openClaim && <ClaimDetailPanel api={api} claimId={openClaim} role="staff" onClose={() => setOpenClaim(null)} onChanged={refresh} />}
    </section>
  );
}
