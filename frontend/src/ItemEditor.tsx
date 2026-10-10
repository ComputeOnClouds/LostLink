import { useEffect, useId, useRef, useState } from 'react';
import { ApiClient, DescriptionSource, GeneratedDescription, ItemLocation, ItemWrite, Report } from './api';
import { LocationPicker } from './LocationPicker';
import { DescriptionDisclosure } from './DescriptionDisclosure';
import { isoToLocalInput, nowLocal } from './time';

export function ItemEditor({
  api,
  kind,
  initial,
  submitLabel,
  onSave,
  onCancel,
}: {
  api: ApiClient;
  kind: 'report' | 'item';
  initial?: Report | null;
  submitLabel: string;
  onSave: (input: ItemWrite) => Promise<void>;
  onCancel?: () => void;
}) {
  const disclosureId = useId();
  const [description, setDescription] = useState(initial?.description || '');
  const [locationZone, setLocationZone] = useState(initial?.locationZone || '');
  const [location, setLocation] = useState<ItemLocation | null>(initial?.location || null);
  const [locationReset, setLocationReset] = useState(0);
  const [searchRadius, setSearchRadius] = useState<number | null>(initial?.searchRadiusMetres ?? null);
  const [eventTime, setEventTime] = useState(initial ? isoToLocalInput(initial.eventTime) : nowLocal());
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [photoKey, setPhotoKey] = useState<string | null>(initial?.photoKey || null);
  const [photoUrl, setPhotoUrl] = useState<string | null>(initial?.photoUrl || null);
  const [source, setSource] = useState<DescriptionSource>(initial?.descriptionSource || (initial?.description ? 'unknown' : 'user'));
  const [generated, setGenerated] = useState<GeneratedDescription | null>(null);
  const [acceptedGeneration, setAcceptedGeneration] = useState<GeneratedDescription | null>(null);
  const [generationBusy, setGenerationBusy] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [confirmKeep, setConfirmKeep] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const automaticAttempt = useRef<string | null>(null);
  const generationVersion = useRef(0);

  function invalidateGeneration() {
    generationVersion.current += 1;
    setGenerated(null);
    setGenerationError(null);
    setGenerationBusy(false);
    setConfirmKeep(false);
  }

  useEffect(() => () => { generationVersion.current += 1; }, []);

  async function generate(key: string) {
    const version = ++generationVersion.current;
    setGenerationBusy(true);
    setGenerationError(null);
    setGenerated(null);
    try {
      const draft = await api.generateDescription(key, crypto.randomUUID(), initial?.itemId);
      if (version === generationVersion.current) setGenerated(draft);
    } catch (err) {
      if (version === generationVersion.current) {
        setGenerationError(err instanceof Error ? err.message : 'Description generation failed.');
      }
    } finally {
      if (version === generationVersion.current) setGenerationBusy(false);
    }
  }

  useEffect(() => {
    if (!photoFile) return;
    let active = true;
    setUploadBusy(true);
    setError(null);
    api.uploadItemPhoto(kind, photoFile)
      .then(async (key) => {
        if (!active) return;
        setPhotoKey(key);
        setPhotoUrl(URL.createObjectURL(photoFile));
        if (!description.trim() && automaticAttempt.current !== key) {
          automaticAttempt.current = key;
          await generate(key);
        }
      })
      .catch((err) => active && setError(err instanceof Error ? err.message : 'Photo upload failed.'))
      .finally(() => active && setUploadBusy(false));
    return () => { active = false; };
    // Each file selection creates exactly one upload and at most one automatic model call.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photoFile]);

  function useGenerated() {
    if (!generated) return;
    setDescription(generated.description);
    setSource('ai');
    setAcceptedGeneration(generated);
    setGenerated(null);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!description.trim() && !photoKey) {
      setError('Add a description or a photo.');
      return;
    }
    if (!location && !locationZone.trim()) {
      setError('Choose a location suggestion or set a point on the map.');
      return;
    }
    if (location && !location.name.trim()) {
      setError('Name the location before saving.');
      return;
    }
    if (searchRadius !== null && !location) {
      setError('Choose a confirmed location before setting a distance limit.');
      return;
    }
    if (generated && !description.trim()) {
      setError('Use the generated description, cancel the preview, or type your own before saving.');
      return;
    }
    setBusy(true);
    try {
      const input: ItemWrite = {
        description: description.trim() || undefined,
        locationZone: locationZone.trim() || null,
        location,
        ...(kind === 'report' ? { searchRadiusMetres: searchRadius } : {}),
        eventTime: eventTime ? new Date(eventTime).toISOString() : undefined,
        photoKey,
        descriptionSource: source,
        descriptionPhotoKey: source === 'ai' || source === 'ai_edited'
          ? (acceptedGeneration?.descriptionPhotoKey || initial?.descriptionPhotoKey || photoKey)
          : null,
        descriptionGeneratedAt: acceptedGeneration?.descriptionGeneratedAt || initial?.descriptionGeneratedAt || null,
        revision: initial?.revision,
        confirmKeepDescription: confirmKeep,
      };
      await onSave(input);
      if (!initial) {
        setDescription('');
        setLocationZone('');
        setLocation(null);
        setSearchRadius(null);
        setLocationReset((version) => version + 1);
        setEventTime(nowLocal());
        setPhotoFile(null);
        setPhotoKey(null);
        setPhotoUrl(null);
        setSource('user');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed.');
    } finally {
      setBusy(false);
    }
  }

  const replacingGeneratedPhoto = Boolean(
    photoKey && initial?.photoKey !== photoKey
    && (initial?.descriptionSource === 'ai' || initial?.descriptionSource === 'ai_edited')
    && initial.descriptionPhotoKey === initial.photoKey
    && description === (initial.description || '')
  );
  const dirty = Boolean(initial && (
    description !== (initial.description || '')
    || locationZone !== (initial.locationZone || '')
    || JSON.stringify(location) !== JSON.stringify(initial.location || null)
    || searchRadius !== (initial.searchRadiusMetres ?? null)
    || eventTime !== isoToLocalInput(initial.eventTime)
    || photoKey !== initial.photoKey
  ));

  return (
    <form onSubmit={submit} className="item-editor">
      <label className="field">
        <span>Description <span className="hint">(optional if you add a photo)</span></span>
        <textarea
          value={description}
          aria-describedby={disclosureId}
          onChange={(event) => {
            const next = event.target.value;
            setDescription(next);
            if ((source === 'ai' || source === 'ai_edited') && next !== (acceptedGeneration?.description || initial?.description)) {
              setSource('ai_edited');
            } else if (source !== 'ai' && source !== 'ai_edited') {
              setSource('user');
            }
          }}
          placeholder={kind === 'report' ? 'e.g. black leather wallet with a red stripe' : 'e.g. dark leather wallet found near the entrance'}
        />
      </label>
      <DescriptionDisclosure id={disclosureId} />

      <LocationPicker key={initial?.itemId || `new-${kind}-${locationReset}`}
        api={api} kind={kind} value={location} onChange={setLocation}
        legacyZone={locationZone} onReplaceLegacy={() => setLocationZone('')} />
      {kind === 'report' && <label className="field">
        <span>Search within</span>
        <select value={searchRadius ?? ''} onChange={(event) => setSearchRadius(event.target.value ? Number(event.target.value) : null)}>
          <option value="">Any distance — rank by proximity</option>
          <option value="500">500 metres</option>
          <option value="1000">1 kilometre</option>
          <option value="2000">2 kilometres</option>
          <option value="5000">5 kilometres</option>
        </select>
        {searchRadius !== null && <p className="meta">Only found items with coordinates inside this radius will be considered.</p>}
      </label>}
      <label className="field">
        <span>{kind === 'report' ? 'Approx. time lost' : 'Time found'}</span>
        <input type="datetime-local" value={eventTime} onChange={(event) => setEventTime(event.target.value)} />
      </label>

      <div className="field photo-field">
        <span>Photo <span className="hint">(optional)</span></span>
        {photoUrl && <img className="photo-preview" src={photoUrl} alt="Current item" />}
        <input type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => {
          const file = event.target.files?.[0];
          if (!file) return;
          invalidateGeneration();
          setUploadBusy(true);
          setPhotoFile(file);
        }} />
        <div className="btn-row compact">
          {photoKey && (
            <button type="button" className="secondary sm" disabled={uploadBusy || generationBusy} onClick={() => void generate(photoKey)}>
              {generationBusy ? 'Generating…' : 'Generate description from photo'}
            </button>
          )}
          {photoKey && <button type="button" className="danger sm" onClick={() => {
            invalidateGeneration();
            setUploadBusy(false);
            setPhotoKey(null);
            setPhotoUrl(null);
            setPhotoFile(null);
          }}>Remove photo</button>}
        </div>
      </div>

      {generated && (
        <div className="generation-preview" aria-live="polite">
          <strong>Generated draft</strong>
          <p>{generated.description}</p>
          <DescriptionDisclosure />
          <div className="btn-row">
            <button type="button" className="sm" onClick={useGenerated}>Use description</button>
            <button type="button" className="secondary sm" onClick={() => photoKey && void generate(photoKey)}>Try again</button>
            <button type="button" className="ghost sm" onClick={() => setGenerated(null)}>Cancel</button>
          </div>
        </div>
      )}
      {generationError && (
        <div className="notice err" role="alert">
          {generationError}
          {photoKey && <button type="button" className="linklike" onClick={() => void generate(photoKey)}>Try again</button>}
        </div>
      )}
      {replacingGeneratedPhoto && (
        <label className="check-row">
          <input type="checkbox" checked={confirmKeep} onChange={(event) => setConfirmKeep(event.target.checked)} />
          <span>The existing generated wording still describes the replacement photo.</span>
        </label>
      )}
      {error && <div className="notice err" role="alert">{error}</div>}
      {confirmDiscard && (
        <div className="notice info" role="alert">
          Discard your unsaved changes?
          <div className="btn-row compact">
            <button type="button" className="danger sm" onClick={onCancel}>Discard changes</button>
            <button type="button" className="secondary sm" onClick={() => setConfirmDiscard(false)}>Keep editing</button>
          </div>
        </div>
      )}
      <div className="btn-row form-actions">
        <button type="submit" disabled={busy || uploadBusy || generationBusy || (replacingGeneratedPhoto && !confirmKeep)}>
          {busy ? 'Saving…' : uploadBusy ? 'Uploading photo…' : submitLabel}
        </button>
        {onCancel && (
          <button type="button" className="secondary" onClick={() => dirty ? setConfirmDiscard(true) : onCancel()}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
