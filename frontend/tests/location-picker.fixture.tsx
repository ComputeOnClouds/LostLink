/** Local component harness only; Vite's production entry never includes this file. */
import React from 'react';
import { createRoot } from 'react-dom/client';
import { ApiClient, Report } from '../src/api';
import { ItemEditor } from '../src/ItemEditor';
import '../src/styles.css';

const params = new URLSearchParams(location.search);
const kind = params.get('kind') === 'item' ? 'item' : 'report';
const api = new ApiClient({ apiUrl: '/test-api', region: 'test', userPoolId: 'test', userPoolClientId: 'test' }, 'fixture');
const initial: Report | null = params.has('legacy') ? {
  itemId: 'legacy-1', type: 'lost', description: 'Black wallet', locationZone: 'zone-library',
  eventTime: null, photoKey: null, status: 'no_match', descriptionSource: 'user', revision: 1,
} : null;
createRoot(document.getElementById('root')!).render(<React.StrictMode>
  <main className="page"><section className="card">
    <h2>{kind === 'report' ? 'Report a lost item' : 'Register a found item'}</h2>
    <ItemEditor api={api} kind={kind} initial={initial} submitLabel="Save item" onSave={async (input) => {
      await fetch('/test-api/save', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) });
    }} />
  </section></main>
</React.StrictMode>);
