import { useCallback, useEffect, useState } from 'react';
import { ApiClient, Claim, MatchSuggestion, Report } from './api';
import { ClaimDetailPanel, ClaimSubmission } from './ClaimWorkflow';
import { DescriptionBlock } from './DescriptionDisclosure';
import { ItemEditor } from './ItemEditor';
import { claimStateLabel, reportStatusLabel } from './labels';
import { formatLocalTime } from './time';
import { useReportMatches } from './useReportMatches';

export function IndividualPortal({ api }: { api: ApiClient }) {
  const { reports, matches, error, refresh, watchReport } = useReportMatches(api);
  const [message, setMessage] = useState<string | null>(null);
  const [editing, setEditing] = useState<Report | null>(null);

  return (
    <div className="grid portal-grid">
      <section className="card">
        <h2>Report a lost item</h2>
        <ItemEditor
          api={api}
          kind="report"
          submitLabel="Submit report"
          onSave={async (input) => {
            const saved = await api.createReport(input);
            setMessage('Report submitted. We’ll notify you if a partner organisation may have it.');
            void watchReport(saved.itemId);
          }}
        />
        {message && <div className="notice ok" role="status">{message}</div>}
      </section>

      <MatchesAndClaims api={api} reports={reports} matches={matches} error={error} refresh={refresh} />

      <section className="card">
        <h2>My reports</h2>
        {reports === null ? <p className="empty">{error ? 'Reports unavailable.' : 'Loading reports…'}</p> : reports.length === 0 ? (
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
                      if (saved.rematching) void watchReport(saved.itemId, saved.revision);
                      else void refresh(true);
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
                        <button type="button" className="danger sm" onClick={async () => { await api.withdrawReport(report.itemId); await refresh(true); }}>Withdraw</button>
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

export function MatchesAndClaims({ api, reports, matches, error, refresh }: {
  api: ApiClient;
  reports: Report[] | null;
  matches: MatchSuggestion[] | null;
  error: string | null;
  refresh: (afterWrite?: boolean) => Promise<void>;
}) {
  const [claims, setClaims] = useState<Claim[] | null>(null);
  const [claimsError, setClaimsError] = useState<string | null>(null);
  const [claiming, setClaiming] = useState<MatchSuggestion | null>(null);
  const [submittedMatches, setSubmittedMatches] = useState<Set<string>>(() => new Set());
  const [openClaim, setOpenClaim] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const refreshClaims = useCallback(async () => {
    try {
      const result = await api.listClaims();
      // Keep locally confirmed revisions while the owner index catches up.
      setClaims((current) => mergeClaims(current, result.claims));
      setClaimsError(null);
    } catch (err) {
      setClaimsError(err instanceof Error ? err.message : 'Please try again.');
    }
  }, [api]);

  useEffect(() => { void refreshClaims(); }, [refreshClaims]);

  async function refreshAfterClaimChange() {
    await Promise.all([refresh(true), refreshClaims()]);
  }

  const groups = new Map<string, MatchSuggestion[]>();
  for (const match of matches ?? []) {
    if (submittedMatches.has(matchKey(match))) continue;
    const group = groups.get(match.queryItemId) ?? [];
    group.push(match);
    groups.set(match.queryItemId, group);
  }
  // Keep the open form mounted if rematching temporarily removes its suggestion.
  const draftMissing = claiming && !matches?.some((match) => sameMatch(claiming, match));
  if (claiming && draftMissing) {
    groups.set(claiming.queryItemId, [...(groups.get(claiming.queryItemId) ?? []), claiming]);
  }

  return (
    <section className="card">
      <div className="section-heading">
        <h2>Potential matches</h2>
        <button type="button" className="secondary sm" onClick={() => void refreshAfterClaimChange()}>Refresh results</button>
      </div>
      {error && <p className="notice err" role="alert">Could not refresh reports and matches. {error} Select Refresh results to retry.</p>}
      {reports?.some((report) => report.status === 'pending_match') && (
        <p className="notice info" role="status">Matching is running in the background. You can refresh results at any time.</p>
      )}
      {matches === null ? <p className="empty">{error ? 'Matches unavailable.' : 'Checking matches…'}</p> : groups.size === 0 ? (
        <p className="empty">{claims?.length || submittedMatches.size
          ? 'No new matches to claim. You can track submitted claims below.'
          : 'No potential matches yet. We’ll notify you if one appears.'}</p>
      ) : (
        <div className="grid">
          {Array.from(groups, ([reportId, group]) => (
            <section key={reportId} aria-labelledby={`matches-${reportId}`}>
              <h3 id={`matches-${reportId}`}>{reports?.find((report) => report.itemId === reportId)?.description || 'Lost report'}</h3>
              <ul className="list">
                {group.sort((a, b) => b.score - a.score).map((match) => {
                  const isDraft = claiming !== null && sameMatch(claiming, match);
                  const score = Math.round(match.score * 100);
                  return (
                    <li key={match.candidateItemId} className="tile">
                      <div className="title">{match.message}</div>
                      <div className="meta">Held by <strong>{match.organisationId}</strong></div>
                      <div className="confidence">
                        <div className="bar" aria-hidden="true"><span style={{ width: `${score}%` }} /></div>
                        <span className="pct">{score}% similarity</span>
                      </div>
                      {isDraft ? (
                        <ClaimSubmission
                          api={api}
                          match={match}
                          available={!draftMissing}
                          onCancel={() => setClaiming(null)}
                          onSubmitted={async (claim) => {
                            // The claim index may lag behind the successful submission.
                            setSubmittedMatches((current) => new Set(current).add(matchKey(match)));
                            setClaims((current) => mergeClaims(current, [claim]));
                            setClaiming((current) => current && sameMatch(current, match) ? null : current);
                            setNote('Claim submitted. The organisation will review your evidence.');
                            await refreshAfterClaimChange();
                          }}
                        />
                      ) : (
                        <div className="btn-row"><button className="sm" onClick={() => setClaiming(match)}>This is mine — submit a claim</button></div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      )}
      {note && <div className="notice ok" role="status">{note}</div>}

      <hr className="divider" />
      <h3>My claims</h3>
      {claimsError && (
        <p className="notice err" role="alert">
          Could not refresh claims. {claimsError}{' '}
          <button type="button" className="secondary sm" onClick={() => void refreshClaims()}>Retry claims</button>
        </p>
      )}
      {claims === null ? <p className="empty">{claimsError ? 'Claims unavailable.' : 'Loading claims…'}</p> : claims.length === 0 ? <p className="empty">No claims yet.</p> : (
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
                  <button className="danger sm" onClick={async () => {
                    const result = await api.cancelClaim(claim.claimId, claim.revision);
                    setClaims((current) => mergeClaims(current, [{ ...claim, state: result.state, revision: claim.revision + 1 }]));
                    await refreshAfterClaimChange();
                  }}>Cancel claim</button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {openClaim && (
        <ClaimDetailPanel api={api} claimId={openClaim} role="claimant" onClose={() => setOpenClaim(null)} onChanged={refreshAfterClaimChange} />
      )}
    </section>
  );
}

function sameMatch(a: MatchSuggestion, b: MatchSuggestion) {
  return a.queryItemId === b.queryItemId && a.candidateItemId === b.candidateItemId;
}

function matchKey(match: MatchSuggestion) {
  return JSON.stringify([match.queryItemId, match.candidateItemId]);
}

function mergeClaims(current: Claim[] | null, incoming: Claim[]) {
  const merged = new Map((current ?? []).map((claim) => [claim.claimId, claim]));
  for (const claim of incoming) {
    const existing = merged.get(claim.claimId);
    if (!existing || claim.revision >= existing.revision) merged.set(claim.claimId, claim);
  }
  return Array.from(merged.values());
}
