import React from 'react';
import { createRoot } from 'react-dom/client';
import { ApiClient } from '../src/api';
import { IndividualPortal } from '../src/IndividualPortal';
import '../src/styles.css';

const api = new ApiClient({ apiUrl: '/test-api', region: 'test', userPoolId: 'test', userPoolClientId: 'test' }, 'fixture');
createRoot(document.getElementById('root')!).render(
  <React.StrictMode><main className="page"><IndividualPortal api={api} /></main></React.StrictMode>,
);
