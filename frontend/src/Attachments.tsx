import { useId, useState } from 'react';
import { ApiClient, Attachment } from './api';

const ALLOWED = ['image/jpeg', 'image/png', 'image/webp', 'application/pdf'];
const MAX_BYTES = 10 * 1024 * 1024;

interface PendingFile {
  id: string;
  file: File;
  state: 'uploading' | 'ready' | 'error';
  key?: string;
  error?: string;
}

export function AttachmentPicker({
  api,
  onChange,
  disabled = false,
}: {
  api: ApiClient;
  onChange: (keys: string[], pending: boolean) => void;
  disabled?: boolean;
}) {
  const inputId = useId();
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [validation, setValidation] = useState<string | null>(null);

  function commit(update: (current: PendingFile[]) => PendingFile[]) {
    setFiles((current) => {
      const next = update(current);
      onChange(
        next.filter((entry) => entry.state === 'ready' && entry.key).map((entry) => entry.key!),
        next.some((entry) => entry.state === 'uploading')
      );
      return next;
    });
  }

  async function upload(entry: PendingFile) {
    try {
      const key = await api.uploadEvidence(entry.file);
      commit((current) => current.map((item) => item.id === entry.id ? { ...item, state: 'ready', key } : item));
    } catch (err) {
      commit((current) => current.map((item) => item.id === entry.id ? {
        ...item,
        state: 'error',
        error: err instanceof Error ? err.message : 'Upload failed',
      } : item));
    }
  }

  function add(selected: FileList | null) {
    setValidation(null);
    if (!selected) return;
    const incoming = Array.from(selected);
    if (files.length + incoming.length > 5) {
      setValidation('Attach up to five files to each submission.');
      return;
    }
    const invalid = incoming.find((file) => !ALLOWED.includes(file.type) || file.size <= 0 || file.size > MAX_BYTES);
    if (invalid) {
      setValidation(`${invalid.name} must be a JPEG, PNG, WebP or PDF no larger than 10 MiB.`);
      return;
    }
    const additions = incoming.map((file) => ({
      id: `${crypto.randomUUID()}`,
      file,
      state: 'uploading' as const,
    }));
    const next = [...files, ...additions];
    commit(() => next);
    additions.forEach((entry) => void upload(entry));
  }

  function remove(id: string) { commit((current) => current.filter((entry) => entry.id !== id)); }

  function retry(entry: PendingFile) {
    const next = files.map((item) => item.id === entry.id ? { ...item, state: 'uploading' as const, error: undefined } : item);
    commit(() => next);
    void upload({ ...entry, state: 'uploading' });
  }

  return (
    <div className="attachment-picker">
      <label className="field" htmlFor={inputId}>
        <span>Attachments <span className="hint">(optional · JPEG, PNG, WebP or PDF · 10 MiB each)</span></span>
      </label>
      <input
        id={inputId}
        type="file"
        accept="image/jpeg,image/png,image/webp,application/pdf"
        multiple
        disabled={disabled || files.length >= 5}
        onChange={(event) => { add(event.target.files); event.currentTarget.value = ''; }}
      />
      {validation && <div className="field-error" role="alert">{validation}</div>}
      {files.length > 0 && (
        <ul className="upload-list" aria-live="polite">
          {files.map((entry) => (
            <li key={entry.id}>
              <span className="file-name">{entry.file.name}</span>
              <span className={`upload-state ${entry.state}`}>
                {entry.state === 'uploading' ? 'Uploading…' : entry.state === 'ready' ? 'Ready' : entry.error}
              </span>
              <span className="file-size">{formatBytes(entry.file.size)}</span>
              {entry.state === 'error' && <button type="button" className="linklike" onClick={() => retry(entry)}>Retry</button>}
              <button type="button" className="linklike danger-link" onClick={() => remove(entry.id)}>Remove</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function AttachmentGallery({ attachments = [] }: { attachments?: Attachment[] }) {
  if (!attachments.length) return null;
  return (
    <div className="attachment-gallery">
      <h4>Attachments</h4>
      <ul>
        {attachments.map((attachment) => (
          <li key={attachment.attachmentId}>
            {attachment.contentType.startsWith('image/') && attachment.downloadUrl ? (
              <img src={attachment.downloadUrl} alt={`Evidence: ${attachment.filename}`} />
            ) : <span className="file-tile" aria-hidden="true">PDF</span>}
            <div>
              <div className="file-name">{attachment.filename}</div>
              <div className="meta">{formatBytes(attachment.size)}</div>
            </div>
            {attachment.downloadUrl ? (
              <a className="button-link secondary sm" href={attachment.downloadUrl} target="_blank" rel="noreferrer">
                {attachment.contentType === 'application/pdf' ? 'Open PDF' : 'View'}
              </a>
            ) : <span className="meta">Unavailable</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function formatBytes(size: number) {
  if (!size) return 'Legacy attachment';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KiB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MiB`;
}
