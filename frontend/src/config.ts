/**
 * Runtime configuration.
 *
 * Fetched from /config.json at startup rather than baked into the build, so the same
 * bundle works against any deployment. The CDK FrontendStack writes config.json into
 * the hosting bucket from the deployed stack outputs (API URL, Cognito ids, region).
 */
export interface RuntimeConfig {
  apiUrl: string;
  region: string;
  userPoolId: string;
  userPoolClientId: string;
}

let cached: RuntimeConfig | null = null;

export async function loadConfig(): Promise<RuntimeConfig> {
  if (cached) return cached;
  const res = await fetch('/config.json', { cache: 'no-store' });
  if (!res.ok) {
    throw new Error(`Failed to load config.json (${res.status})`);
  }
  cached = (await res.json()) as RuntimeConfig;
  return cached;
}
