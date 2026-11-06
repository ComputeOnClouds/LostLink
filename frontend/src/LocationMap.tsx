import { useEffect, useRef, useState } from 'react';
import type { Map, Marker } from 'leaflet';
import { ItemLocation } from './api';
import 'leaflet/dist/leaflet.css';

export const SERVICE_BOUNDS = [[1.13, 103.50], [1.57, 104.12]] as const;
export function inServiceArea(latitude: number, longitude: number) {
  return Number.isFinite(latitude) && Number.isFinite(longitude)
    && latitude >= 1.13 && latitude <= 1.57 && longitude >= 103.50 && longitude <= 104.12;
}

export default function LocationMap({ location, onSelect }: {
  location: ItemLocation | null;
  onSelect: (latitude: number, longitude: number) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<Map | null>(null);
  const marker = useRef<Marker | null>(null);
  const callback = useRef(onSelect);
  callback.current = onSelect;
  const currentLocation = useRef(location);
  currentLocation.current = location;
  const [error, setError] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let active = true;
    void import('leaflet').then((L) => {
      if (!active || !container.current) return;
      const initial = currentLocation.current;
      const instance = L.map(container.current, {
        minZoom: 11, maxZoom: 19, scrollWheelZoom: false,
        maxBounds: [[1.13, 103.50], [1.57, 104.12]], maxBoundsViscosity: 1,
      }).setView(initial ? [initial.latitude, initial.longitude] : [1.3521, 103.8198], initial ? 16 : 11);
      map.current = instance;
      instance.attributionControl.setPrefix(false);
      L.tileLayer('https://www.onemap.gov.sg/maps/tiles/Default_HD/{z}/{x}/{y}.png', {
        minZoom: 11, maxZoom: 19,
        attribution: '<img src="https://www.onemap.gov.sg/web-assets/images/logo/om_logo.png" alt="" width="20" height="20" style="vertical-align:middle" /> <a href="https://www.onemap.gov.sg/" target="_blank" rel="noopener noreferrer">OneMap</a> © contributors | <a href="https://www.sla.gov.sg/" target="_blank" rel="noopener noreferrer">Singapore Land Authority</a>',
      }).on('tileerror', () => active && setError(true)).addTo(instance);
      // Inline marker icon avoids bundler-sensitive Leaflet image URLs.
      const icon = L.divIcon({
        className: 'location-pin', iconSize: [30, 40], iconAnchor: [15, 38],
        html: '<svg viewBox="0 0 30 40" aria-hidden="true"><path d="M15 38C12 33 2 22 2 15a13 13 0 0 1 26 0c0 7-10 18-13 23Z" fill="#075d55" stroke="white" stroke-width="2"/><circle cx="15" cy="15" r="4" fill="white"/></svg>',
      });
      const pin = L.marker(initial ? [initial.latitude, initial.longitude] : [1.3521, 103.8198], {
        icon, draggable: true, keyboard: true, title: 'Selected location', alt: 'Selected location pin',
      });
      marker.current = pin;
      if (initial) pin.addTo(instance);
      const select = (latitude: number, longitude: number) => {
        if (inServiceArea(latitude, longitude)) callback.current(latitude, longitude);
        else if (currentLocation.current) pin.setLatLng([currentLocation.current.latitude, currentLocation.current.longitude]);
      };
      instance.on('click', (event) => select(event.latlng.lat, event.latlng.lng));
      pin.on('dragend', () => { const point = pin.getLatLng(); select(point.lat, point.lng); });
      setReady(true);
    }).catch(() => active && setError(true));
    return () => {
      active = false;
      map.current?.remove();
      map.current = null;
      marker.current = null;
    };
  }, []);

  useEffect(() => {
    if (!ready || !map.current || !marker.current) return;
    if (location) {
      const point: [number, number] = [location.latitude, location.longitude];
      marker.current.setLatLng(point).addTo(map.current);
      map.current.setView(point, Math.max(map.current.getZoom(), 16), { animate: false });
    } else marker.current.remove();
  }, [location?.latitude, location?.longitude, ready]);

  return <>
    <div ref={container} className="location-map" role="region" aria-label="Singapore location map" />
    {error && <p className="field-error" role="status">The map could not fully load. You can still choose a suggestion or enter coordinates below.</p>}
  </>;
}
