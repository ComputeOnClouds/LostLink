// Vite config for the local Docker stack (docs/LOCAL.md). Wraps frontend/vite.config.ts,
// which docker-compose.yml mounts next to this file, without changing it.
import { mergeConfig } from 'vite';
import base from './vite.config';

export default mergeConfig(base, {
  // The local backend generates config.json...
  server: { proxy: { '/config.json': 'http://backend:8080' } },
  // ...and stands in for Cognito: send the Cognito SDK's calls there instead of AWS.
  plugins: [{
    name: 'local-cognito',
    transformIndexHtml: () => [{
      tag: 'script',
      injectTo: 'head-prepend',
      children: `const f = window.fetch.bind(window);
window.fetch = (url, init) => f(/^https:\\/\\/cognito-idp\\./.test(url) ? 'http://localhost:8080/cognito' : url, init);`,
    }],
  }],
});
