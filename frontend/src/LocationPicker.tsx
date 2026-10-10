import { Component, lazy, ReactNode, Suspense, useEffect, useId, useRef, useState } from 'react';
import { ApiClient, ApiError, ItemLocation } from './api';

const LocationMap = lazy(() => import('./LocationMap'));
class MapBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed ? <p className="field-error" role="status">The map could not load. Choose a suggestion or enter coordinates below.</p> : this.props.children;
  }
}
function inServiceArea(latitude: number, longitude: number) {
  return Number.isFinite(latitude) && Number.isFinite(longitude)
    && latitude >= 1.13 && latitude <= 1.57 && longitude >= 103.50 && longitude <= 104.12;
}

export function LocationPicker({ api, value, onChange, kind, legacyZone, onReplaceLegacy }: {
  api: ApiClient;
  value: ItemLocation | null;
  onChange: (location: ItemLocation | null) => void;
  kind: 'report' | 'item';
  legacyZone?: string;
  onReplaceLegacy: () => void;
}) {
  const id = useId();
  const [query, setQuery] = useState(value?.name || '');
  const [suggestions, setSuggestions] = useState<ItemLocation[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [searched, setSearched] = useState(false);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [showMap, setShowMap] = useState(Boolean(value));
  const [manual, setManual] = useState(value?.selectionMethod === 'map');
  const [retry, setRetry] = useState(0);
  const [coordinates, setCoordinates] = useState({ latitude: String(value?.latitude ?? ''), longitude: String(value?.longitude ?? '') });
  const [coordinateError, setCoordinateError] = useState('');
  const apiRef = useRef(api);
  apiRef.current = api;
  const version = useRef(0);
  const confirmed = Boolean(value && value.name === query);

  useEffect(() => {
    const requestVersion = ++version.current;
    const controller = new AbortController();
    setSuggestions([]); setActive(-1); setError(''); setSearched(false); setBusy(false);
    if (confirmed || manual || query.trim().length < 2) return () => controller.abort();
    setBusy(true);
    const timer = window.setTimeout(() => {
      void apiRef.current.searchLocations(query.trim(), controller.signal).then(({ suggestions: results }) => {
        if (requestVersion !== version.current) return;
        setSuggestions(results); setSearched(true);
      }).catch((err) => {
        if (requestVersion !== version.current || controller.signal.aborted) return;
        setError(err instanceof ApiError && err.status === 429
          ? 'Place search is busy. Try again shortly or choose on the map.'
          : err instanceof Error ? err.message : 'Place search failed. Try again or choose on the map.');
      }).finally(() => { if (requestVersion === version.current) setBusy(false); });
    }, 300);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [query, confirmed, manual, retry]);

  useEffect(() => {
    setCoordinates({ latitude: String(value?.latitude ?? ''), longitude: String(value?.longitude ?? '') });
  }, [value?.latitude, value?.longitude]);

  function select(location: ItemLocation) {
    ++version.current;
    onReplaceLegacy(); onChange(location); setQuery(location.name);
    setSuggestions([]); setOpen(false); setBusy(false); setError(''); setManual(false); setShowMap(true);
  }

  function movePin(latitude: number, longitude: number) {
    onReplaceLegacy(); setManual(true); setOpen(false); setCoordinateError('');
    onChange({ ...value, name: query.trim(), latitude, longitude,
      provider: value?.provider || 'manual', selectionMethod: 'map', address: null, providerPlaceId: null });
  }

  const expanded = open && suggestions.length > 0;
  return <div className="location-picker">
    <label className="field" htmlFor={`${id}-search`}>
      <span>{kind === 'report' ? 'Where did you lose it?' : 'Where was it found?'}*</span>
      <input id={`${id}-search`} role="combobox" autoComplete="off" maxLength={manual ? 200 : 120}
        value={query} placeholder={manual ? 'Name this location' : 'Search a place, address or postal code'}
        aria-autocomplete={manual ? 'none' : 'list'} aria-expanded={expanded}
        aria-controls={`${id}-results`} aria-describedby={`${id}-help ${id}-status`}
        aria-activedescendant={expanded && active >= 0 ? `${id}-option-${active}` : undefined}
        onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
        onChange={(event) => {
          ++version.current;
          const next = event.target.value;
          setQuery(next); setOpen(true);
          if (manual && value) onChange({ ...value, name: next });
          else onChange(null);
          onReplaceLegacy();
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') { setOpen(false); return; }
          if (event.key === 'Enter' && expanded) {
            event.preventDefault();
            if (active >= 0) select(suggestions[active]);
          }
          if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && suggestions.length) {
            event.preventDefault(); setOpen(true);
            setActive((index) => event.key === 'ArrowDown' ? (index + 1) % suggestions.length : (index <= 0 ? suggestions.length - 1 : index - 1));
          }
        }} />
    </label>
    <ul id={`${id}-results`} role="listbox" aria-label="Location suggestions" className="location-results" hidden={!expanded}>
      {suggestions.map((location, index) => <li key={`${location.latitude}-${location.longitude}-${index}`}
        role="option" id={`${id}-option-${index}`} aria-selected={active === index}
        onMouseDown={(event) => event.preventDefault()} onClick={() => select(location)}>
        <strong>{location.name}</strong><span>{location.address}</span>
      </li>)}
    </ul>
    <p id={`${id}-help`} className="meta location-help">
      {manual ? 'Name the place and choose its point on the map or enter coordinates.' : 'Choose a suggestion to confirm the location, or choose on the map.'}
    </p>
    <div id={`${id}-status`} aria-live="polite" className="meta location-status">
      {busy ? 'Searching places…' : error ? <><span className="field-error">{error}</span> <button type="button" className="linklike" onClick={() => setRetry((count) => count + 1)}>Try again</button></>
        : searched && !suggestions.length ? 'No places found. Try an address or choose on the map.'
        : value ? (value.selectionMethod === 'map' ? 'Pin set manually. Check the name and position before saving.' : `Selected: ${value.name}`)
        : legacyZone ? `Saved legacy location: ${legacyZone}. Choose a place to upgrade it.` : ''}
    </div>
    <div className="btn-row compact">
      <button type="button" className="secondary sm" onClick={() => { setShowMap(true); setManual(true); setOpen(false); }}>
        {showMap ? 'Choose a different point' : 'Choose on map'}
      </button>
      {(value || manual) && <button type="button" className="ghost sm" onClick={() => {
        ++version.current; onChange(null); onReplaceLegacy(); setQuery(''); setManual(false); setOpen(false);
      }}>Search another place</button>}
    </div>
    {showMap && <div className="location-map-wrap">
      <p className="meta">Click the map or drag the pin to adjust the {kind === 'report' ? 'loss' : 'find'} location.</p>
      <MapBoundary><Suspense fallback={<div className="location-map-loading" role="status">Loading map…</div>}>
        <LocationMap location={value} onSelect={movePin} />
      </Suspense></MapBoundary>
      <details className="location-coordinates">
        <summary>Enter coordinates instead</summary>
        <div className="location-coordinate-fields">
          <label className="field"><span>Latitude</span><input type="number" step="any" value={coordinates.latitude}
            onChange={(event) => setCoordinates({ ...coordinates, latitude: event.target.value })} /></label>
          <label className="field"><span>Longitude</span><input type="number" step="any" value={coordinates.longitude}
            onChange={(event) => setCoordinates({ ...coordinates, longitude: event.target.value })} /></label>
        </div>
        <button type="button" className="secondary sm" onClick={() => {
          const latitude = Number(coordinates.latitude), longitude = Number(coordinates.longitude);
          if (!coordinates.latitude || !coordinates.longitude || !inServiceArea(latitude, longitude)) {
            setCoordinateError('Enter latitude and longitude within the Singapore service area.'); return;
          }
          movePin(latitude, longitude);
        }}>Set location pin</button>
        {coordinateError && <p className="field-error" role="alert">{coordinateError}</p>}
      </details>
    </div>}
    {value && <label className="field location-note"><span>Landmark or floor <span className="hint">(optional)</span></span>
      <input maxLength={500} value={value.note || ''} placeholder="e.g. Level 2, near the entrance"
        onChange={(event) => onChange({ ...value, note: event.target.value })} />
    </label>}
    <p className="location-attribution">Place and map data from <a href="https://www.onemap.gov.sg/" target="_blank" rel="noopener noreferrer">OneMap / Singapore Land Authority</a>, under the <a href="https://www.onemap.gov.sg/legal/opendatalicence.html" target="_blank" rel="noopener noreferrer">Singapore Open Data Licence</a>.</p>
  </div>;
}
