import { useEffect, useRef, useState } from 'react';
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
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [editing, setEditing] = useState<Report | null>(null);

  async function refreshReports(background = false) {
    if (!background) setLoading(true);
    try { setReports((await api.listReports()).reports); setError(null); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not load reports."); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    void refreshReports();
    const timer = window.setInterval(() => { if (!document.hidden) void refreshReports(true); }, 10000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="grid portal-grid">
      <section className="card">
        <h2>Find your lost item</h2>
        <p>Describe it once. We search partner inventories, then staff check your ownership evidence before arranging collection.</p>
        <ItemEditor
          api={api}
          kind="report"
          submitLabel="Submit report"
          onSave={async (input) => {
            await api.createReport(input);
            setMessage('Search started. Matches will appear automatically below.');
            setVersion((v) => v + 1);
            await refreshReports();
          }}
        />
        {message && <div className="notice ok" role="status">{message}</div>}
      </section>

      <MatchesAndClaims api={api} reports={reports} version={version} />

      <section className="card">
        <h2>My reports</h2>
        {error && <div className="notice err" role="alert">{error} <button onClick={() => void refreshReports()}>Try again</button></div>}
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
                    <div className="meta">{report.location?.name || report.locationZone} · {formatLocalTime(report.eventTime)}</div>
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

function MatchesAndClaims({ api, reports, version }: { api: ApiClient; reports: Report[]; version: number }) {
  const [matches, setMatches] = useState<MatchSuggestion[]>([]);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [loading, setLoading] = useState(true);
  const [claiming, setClaiming] = useState<MatchSuggestion | null>(null);
  const [openClaim, setOpenClaim] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const refreshSequence = useRef(0);
  async function refresh(background = false) {
    const requestId = ++refreshSequence.current;
    if (!background) setLoading(true);
    const results = await Promise.allSettled([
      api.listMatches().then((result) => {
        if (requestId !== refreshSequence.current) return;
        setMatches(result.matches.sort((a, b) => a.queryItemId.localeCompare(b.queryItemId) || b.score - a.score || a.candidateItemId.localeCompare(b.candidateItemId)));
      }),
      api.listClaims().then((result) => {
        if (requestId !== refreshSequence.current) return;
        setClaims(result.claims.sort((a, b) => (b.updatedAt || "").localeCompare(a.updatedAt || "")));
      }),
    ]);
    if (requestId !== refreshSequence.current) return;
    const failure = results.find((result) => result.status === 'rejected');
    setError(failure?.status === 'rejected' ? (failure.reason instanceof Error ? failure.reason.message : 'Could not refresh all results. Try again.') : null);
    setLoading(false);
  }

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => { if (!document.hidden) void refresh(true); }, 5000);
    return () => window.clearInterval(timer);
  }, [version]);

  const reportName = (id: string) => reports.find((r) => r.itemId === id)?.description || "Photo-based lost report";

  return (
    <section className="card">
      <div className="section-heading"><h2>Potential matches</h2><button className="secondary sm" disabled={loading} onClick={() => void refresh()}>Refresh status</button></div>
      <p className="meta">Search → ownership evidence → staff review → collection. Status updates automatically.</p>
      {error && <div className="notice err" role="alert">{error}</div>}
      {loading ? <p className="empty">Checking matches…</p> : matches.length === 0 ? (
        <p className="empty">No potential matches yet. We’ll notify you if one appears.</p>
      ) : (
        <ul className="list">
          {matches.map((match) => (
            <li key={`${match.queryItemId}:${match.candidateItemId}`} className="tile">
              <div className="title">For your report: {reportName(match.queryItemId)}</div>
              <p>{match.message}</p>
              <div className="meta">Held by <strong>{match.organisationId}</strong></div>
              <div className="confidence" aria-label={`${Math.round(match.score * 100)} percent match`}>
                <div className="bar"><span style={{ width: `${Math.round(match.score * 100)}%` }} /></div>
                <span className="pct">{Math.round(match.score * 100)}% match</span>
              </div>
              {claiming?.candidateItemId === match.candidateItemId && claiming?.queryItemId === match.queryItemId ? (
                <ClaimSubmission
                  api={api}
                  match={match}
                  onCancel={() => setClaiming(null)}
                  onSubmitted={async (created) => {
                    ++refreshSequence.current;
                    setClaims((previous) => [created, ...previous.filter((claim) => claim.claimId !== created.claimId)]);
                    setClaiming(null);
                    setNote('Claim submitted. The organisation will review your evidence.');
                    await refresh(true);
                  }}
                />
              ) : (
                <div className="btn-row">{claims.some((c) => c.queryItemId === match.queryItemId && c.candidateItemId === match.candidateItemId && !['cancelled', 'rejected'].includes(c.state))
                  ? <span className="notice info">Claim already submitted — follow its progress below.</span>
                  : <button className="sm" onClick={() => setClaiming(match)}>Verify ownership</button>}</div>
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
                <div><strong>{reportName(claim.queryItemId)}</strong><div className="meta">Claim to {claim.organisationId}</div></div>
                <span className={`badge ${claim.state}`}>{claimStateLabel(claim.state)}</span>
              </div>
              {claim.item ? (
                <div className="verified-summary">
                  <DescriptionBlock description={claim.item.description} />
                  <p>{claim.collection}</p>
                </div>
              ) : <div className="hidden-note">{claim.state === "submitted" ? "Waiting for staff to review your proof. No action needed." : claim.state === "info_requested" ? "Staff need more proof. Open your claim to read the question and reply." : claim.state === "rejected" ? "Claim declined. Open it to read the staff response." : "This claim is cancelled."}</div>}
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
