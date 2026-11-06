import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ApiClient, ApiError, Claim, MatchSuggestion, StaffClaim } from './api';
import { AttachmentGallery, AttachmentPicker } from './Attachments';
import { DescriptionBlock } from './DescriptionDisclosure';
import { claimStateLabel } from './labels';
import { formatLocalTime } from './time';

export function ClaimSubmission({
  api,
  match,
  onSubmitted,
  onCancel,
}: {
  api: ApiClient;
  match: MatchSuggestion;
  onSubmitted: () => Promise<void>;
  onCancel: () => void;
}) {
  const [text, setText] = useState('');
  const [keys, setKeys] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!text.trim() && !keys.length) {
      setError('Describe your proof of ownership or attach at least one file.');
      return;
    }
    setBusy(true);
    try {
      await api.submitClaim({
        queryItemId: match.queryItemId,
        candidateItemId: match.candidateItemId,
        evidenceText: text.trim(),
        evidenceKeys: keys,
      });
      await onSubmitted();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Claim submission failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="inline-form claim-form" onSubmit={submit}>
      <h4>Submit an ownership claim</h4>
      <p className="form-intro">Share details only the owner would know. Staff will review them privately.</p>
      <label className="field">
        <span>Proof of ownership</span>
        <textarea value={text} onChange={(event) => setText(event.target.value)} placeholder="Distinguishing marks, receipt details, contents, or another private detail" autoFocus />
      </label>
      <AttachmentPicker api={api} onChange={(next, pending) => { setKeys(next); setUploading(pending); }} />
      {error && <div className="notice err" role="alert">{error}</div>}
      <div className="btn-row">
        <button type="submit" disabled={busy || uploading}>{busy ? 'Submitting…' : 'Submit claim'}</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

export function ClaimDetailPanel({
  api,
  claimId,
  role,
  onClose,
  onChanged,
}: {
  api: ApiClient;
  claimId: string;
  role: 'claimant' | 'staff';
  onClose: () => void;
  onChanged: () => Promise<void>;
}) {
  const [claim, setClaim] = useState<Claim | StaffClaim | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState('');
  const [question, setQuestion] = useState('');
  const [rejectNote, setRejectNote] = useState('');
  const [keys, setKeys] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLElement>(null);

  async function refresh() {
    setLoading(true);
    try {
      setClaim(role === 'staff' ? await api.getOrgClaim(claimId) : await api.getClaim(claimId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load this claim.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const root = document.getElementById('root');
    const previousOverflow = document.body.style.overflow;
    root?.setAttribute('inert', '');
    root?.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
        return;
      }
      if (event.key !== 'Tab' || !panelRef.current) return;
      const focusable = Array.from(panelRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
      ));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      root?.removeAttribute('inert');
      root?.removeAttribute('aria-hidden');
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [claimId]);

  async function claimantReply(event: React.FormEvent) {
    event.preventDefault();
    if (!claim || (!reply.trim() && !keys.length)) {
      setError('Add a reply or at least one attachment.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.respondToClaim(claim.claimId, reply.trim(), keys, claim.revision);
      setReply('');
      setKeys([]);
      await refresh();
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reply failed.');
      if (err instanceof ApiError && err.status === 409) await refresh();
    } finally { setBusy(false); }
  }

  async function staffAction(action: 'request-info' | 'approve' | 'reject' | 'reserve' | 'handover') {
    if (!claim) return;
    const message = action === 'request-info' ? question.trim() : action === 'reject' ? rejectNote.trim() : undefined;
    if (action === 'request-info' && !message) {
      setError('Enter the information you need from the claimant.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.claimAction(claim.claimId, action, claim.revision, message);
      if (action === 'request-info') setQuestion('');
      if (action === 'reject') setRejectNote('');
      await refresh();
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed.');
      if (err instanceof ApiError && err.status === 409) await refresh();
    } finally { setBusy(false); }
  }

  const messages = [...(claim?.messages || [])].sort((a, b) => a.at.localeCompare(b.at));

  return createPortal(
    <div className="panel-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section ref={panelRef} className="detail-panel" role="dialog" aria-modal="true" aria-labelledby="claim-panel-title">
        <header className="panel-header">
          <div>
            <h2 id="claim-panel-title">Claim details</h2>
            {claim && <span className={`badge ${claim.state}`}>{claimStateLabel(claim.state)}</span>}
          </div>
          <button ref={closeRef} type="button" className="secondary sm" onClick={onClose}>Close</button>
        </header>
        <div className="panel-body">
          {loading && <p className="empty">Loading claim…</p>}
          {error && <div className="notice err" role="alert">{error}</div>}
          {claim && (
            <>
              <dl className="summary-list">
                <div><dt>Organisation</dt><dd>{claim.organisationId}</dd></div>
                <div><dt>Updated</dt><dd>{formatLocalTime(claim.updatedAt)}</dd></div>
              </dl>
              <section className="detail-section">
                <h3>Original ownership evidence</h3>
                <p className="message-copy">{claim.evidenceText || 'Files submitted without a written note.'}</p>
                <AttachmentGallery attachments={claim.attachments} />
              </section>

              {claim.item && (
                <section className="detail-section verified-item">
                  <h3>Verified item</h3>
                  {claim.item.photoUrl && <img className="photo-preview" src={claim.item.photoUrl} alt="Verified found item" />}
                  <DescriptionBlock description={claim.item.description} />
                  <p className="meta">{claim.item.location?.name || claim.item.locationZone}</p>
                  {claim.collection && <p>{claim.collection}</p>}
                </section>
              )}

              <section className="detail-section">
                <h3>Conversation</h3>
                {messages.length === 0 ? <p className="empty">No messages yet.</p> : (
                  <ol className="conversation">
                    {messages.map((message, index) => (
                      <li key={`${message.at}-${index}`} className={message.from}>
                        <div className="message-meta"><strong>{message.from === 'staff' ? 'Organisation staff' : 'Claimant'}</strong><time>{formatLocalTime(message.at)}</time></div>
                        {message.text && <p>{message.text}</p>}
                        <AttachmentGallery attachments={message.attachments} />
                      </li>
                    ))}
                  </ol>
                )}
              </section>

              {role === 'claimant' && claim.state === 'info_requested' && (
                <form className="detail-section action-box" onSubmit={claimantReply}>
                  <h3>Information requested</h3>
                  <p>Reply to return this claim to staff review.</p>
                  <label className="field"><span>Your reply</span><textarea value={reply} onChange={(event) => setReply(event.target.value)} /></label>
                  <AttachmentPicker api={api} onChange={(next, pending) => { setKeys(next); setUploading(pending); }} />
                  <button disabled={busy || uploading}>{busy ? 'Sending…' : 'Send reply'}</button>
                </form>
              )}
              {role === 'claimant' && claim.state === 'submitted' && <div className="notice info">Awaiting staff review.</div>}

              {role === 'staff' && claim.state === 'submitted' && (
                <section className="detail-section action-box">
                  <h3>Review claim</h3>
                  <label className="field"><span>Question for claimant</span><textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask for a specific detail" /></label>
                  <button type="button" className="secondary" disabled={busy} onClick={() => void staffAction('request-info')}>Request information</button>
                  <div className="decision-row">
                    <button type="button" disabled={busy} onClick={() => void staffAction('approve')}>Approve ownership</button>
                    <label className="field"><span>Rejection note <span className="hint">(optional)</span></span><input value={rejectNote} onChange={(event) => setRejectNote(event.target.value)} /></label>
                    <button type="button" className="danger" disabled={busy} onClick={() => void staffAction('reject')}>Reject claim</button>
                  </div>
                </section>
              )}
              {role === 'staff' && claim.state === 'info_requested' && (
                <section className="detail-section action-box">
                  <p>Waiting for the claimant to reply. You can still reject the claim if it cannot proceed.</p>
                  <label className="field"><span>Rejection note <span className="hint">(optional)</span></span><input value={rejectNote} onChange={(event) => setRejectNote(event.target.value)} /></label>
                  <button type="button" className="danger" disabled={busy} onClick={() => void staffAction('reject')}>Reject claim</button>
                </section>
              )}
              {role === 'staff' && claim.state === 'approved' && (
                <div className="detail-section action-box btn-row">
                  <button disabled={busy} onClick={() => void staffAction('reserve')}>Reserve for collection</button>
                  <button className="secondary" disabled={busy} onClick={() => void staffAction('handover')}>Record handover</button>
                </div>
              )}
              {role === 'staff' && claim.state === 'reserved' && (
                <div className="detail-section action-box"><button disabled={busy} onClick={() => void staffAction('handover')}>Record handover</button></div>
              )}
            </>
          )}
        </div>
      </section>
    </div>,
    document.body
  );
}
