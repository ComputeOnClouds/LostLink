import { useEffect, useState } from 'react';
import { ApiClient, Claim, MatchSuggestion, Report } from './api';
import { ClaimDetailPanel, ClaimSubmission } from './ClaimWorkflow';
import { DescriptionBlock } from './DescriptionDisclosure';
import { ItemEditor } from './ItemEditor';
import { claimStateLabel, reportStatusLabel } from './labels';
import { formatLocalTime } from './time';

export function IndividualPortal({ api }: { api: ApiClient }) {
  const [reports, setReports] = useState<Report[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [editing, setEditing] = useState<Report | null>(null);

  async function refreshReports() {
    setLoading(true);
    try { setReports((await api.listReports()).reports); }
    finally { setLoading(false); }
  }

  useEffect(() => { void refreshReports(); }, []);

  return (
    <div className="grid portal-grid">
      <section className="card">
        <h2>Report a lost item</h2>
        <ItemEditor
          api={api}
          kind="report"
          submitLabel="Submit report"
          onSave={async (input) => {
            await api.createReport(input);
            setMessage('Report submitted. We’ll notify you if a partner organisation may have it.');
            await refreshReports();
          }}
        />
        {message && <div className="notice ok" role="status">{message}</div>}
      </section>

      <MatchesAndClaims api={api} />

      <section className="card">
        <h2>My reports</h2>
        {loading ? <p className="empty">Loading reports…</p> : reports.length === 0 ? (
          <p className="empty">No reports yet. Your first report will appear here.</p>
        ) : (
          <ul className="list">
            {reports.map((report) => (
              <li key={report.itemId} className="tile">
                {editing?.itemId === report.itemId ? (
                  <ItemEditor
                    api={api}
                    kind="report"
                    initial={editing}
                    submitLabel="Save changes"
                    onCancel={() => setEditing(null)}
                    onSave={async (input) => {
                      const saved = await api.updateReport(report.itemId, input);
                      setMessage(saved.rematching ? 'Report saved. We’re checking matches again.' : 'Report saved.');
                      setEditing(null);
                      await refreshReports();
                    }}
                  />
                ) : (
                  <>
                    <div className="tile-heading">
                      <DescriptionBlock description={report.description} />
                      <span className={`badge ${report.status}`}>{reportStatusLabel(report.status)}</span>
                    </div>
                    <div className="meta">{report.locationZone} · {formatLocalTime(report.eventTime)}</div>
                    <div className="btn-row">
                      {report.status !== 'withdrawn' && (
                        <button type="button" className="secondary sm" onClick={async () => setEditing(await api.getReport(report.itemId))}>Edit</button>
                      )}
                      {report.status !== 'withdrawn' && (
                        <button type="button" className="danger sm" onClick={async () => { await api.withdrawReport(report.itemId); await refreshReports(); }}>Withdraw</button>
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

function MatchesAndClaims({ api }: { api: ApiClient }) {
  const [matches, setMatches] = useState<MatchSuggestion[]>([]);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [loading, setLoading] = useState(true);
  const [claiming, setClaiming] = useState<MatchSuggestion | null>(null);
  const [openClaim, setOpenClaim] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      const [matchResult, claimResult] = await Promise.all([api.listMatches(), api.listClaims()]);
      setMatches(matchResult.matches);
      setClaims(claimResult.claims);
    } finally { setLoading(false); }
  }

  useEffect(() => { void refresh(); }, []);

  return (
    <section className="card">
      <h2>Potential matches</h2>
      {loading ? <p className="empty">Checking matches…</p> : matches.length === 0 ? (
        <p className="empty">No potential matches yet. We’ll notify you if one appears.</p>
      ) : (
        <ul className="list">
          {matches.map((match) => (
            <li key={`${match.queryItemId}:${match.candidateItemId}`} className="tile">
              <div className="title">{match.message}</div>
              <div className="meta">Held by <strong>{match.organisationId}</strong></div>
              <div className="confidence" aria-label={`${Math.round(match.score * 100)} percent match`}>
                <div className="bar"><span style={{ width: `${Math.round(match.score * 100)}%` }} /></div>
                <span className="pct">{Math.round(match.score * 100)}% match</span>
              </div>
              {claiming?.candidateItemId === match.candidateItemId ? (
                <ClaimSubmission
                  api={api}
                  match={match}
                  onCancel={() => setClaiming(null)}
                  onSubmitted={async () => {
                    setClaiming(null);
                    setNote('Claim submitted. The organisation will review your evidence.');
                    await refresh();
                  }}
                />
              ) : (
                <div className="btn-row"><button className="sm" onClick={() => setClaiming(match)}>This is mine — submit a claim</button></div>
              )}
            </li>
          ))}
        </ul>
      )}
      {note && <div className="notice ok" role="status">{note}</div>}

      <hr className="divider" />
      <h3>My claims</h3>
      {claims.length === 0 ? <p className="empty">No claims yet.</p> : (
        <ul className="list">
          {claims.map((claim) => (
            <li key={claim.claimId} className="tile">
              <div className="tile-heading">
                <div>Claim to <strong>{claim.organisationId}</strong></div>
                <span className={`badge ${claim.state}`}>{claimStateLabel(claim.state)}</span>
              </div>
              {claim.item ? (
                <div className="verified-summary">
                  <DescriptionBlock description={claim.item.description} />
                  <p>{claim.collection}</p>
                </div>
              ) : <div className="hidden-note">Item details stay hidden until the organisation approves your claim.</div>}
              <div className="btn-row">
                <button className="secondary sm" onClick={() => setOpenClaim(claim.claimId)}>View claim</button>
                {['submitted', 'info_requested'].includes(claim.state) && (
                  <button className="danger sm" onClick={async () => { await api.cancelClaim(claim.claimId, claim.revision); await refresh(); }}>Cancel claim</button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {openClaim && (
        <ClaimDetailPanel api={api} claimId={openClaim} role="claimant" onClose={() => setOpenClaim(null)} onChanged={refresh} />
      )}
    </section>
  );
}
