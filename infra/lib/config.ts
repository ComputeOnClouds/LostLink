/**
 * Central configuration for the LostLink infrastructure.
 *
 * Region and naming conventions are fixed here so every stack is consistent. Match
 * weights/thresholds live here too and are injected into the worker Lambda as
 * environment variables (see RATIONALE ADR-005). The evaluation harness mirrors these
 * defaults independently for variant sweeps.
 */

export interface MatchConfig {
  /** Weights for the blended score. w_image is 0 today (RATIONALE ADR-004). */
  readonly weightText: string;
  readonly weightImage: string;
  readonly weightLocation: string;
  readonly weightTime: string;
  /** Notification threshold for the active (text+location+time) profile. */
  readonly threshold: string;
  /** Which CandidateRetriever the worker uses (bruteforce | ann). */
  readonly retriever: string;
  readonly locationHalfDistanceMetres: string;
}

export interface LostLinkConfig {
  readonly appName: string;
  readonly region: string;
  readonly match: MatchConfig;
  /**
   * Verified SES sender identity for notifications. Override via the SENDER_EMAIL env
   * var at deploy time, e.g. `SENDER_EMAIL=you@example.com npx cdk deploy ...`. In the
   * SES sandbox this address must be verified (click the link SES emails you), and
   * recipients must also be verified unless they are the mailbox simulator
   * (*@simulator.amazonses.com). See RATIONALE ADR-021.
   */
  readonly senderEmail: string;
  /** Public web app URL (CloudFront), linked in notification emails. */
  readonly cloudFrontUrl: string;
}

/** Fixed application name used to prefix resources for easy identification. */
const APP_NAME = 'LostLink';

/**
 * Region default. Override with the CDK_DEFAULT_REGION env var if needed.
 * ap-southeast-2 (Sydney) — chosen to stay within the developer's free-tier usage.
 * Note: Amazon Bedrock model availability varies by region; confirm Claude + Titan
 * Text Embeddings are available here (or configure a cross-region Bedrock call in the
 * worker) before Task 7.
 */
const DEFAULT_REGION = process.env.CDK_DEFAULT_REGION ?? 'ap-southeast-2';

export const config: LostLinkConfig = {
  appName: APP_NAME,
  region: DEFAULT_REGION,
  match: {
    weightText: '0.6',
    weightImage: '0.0', // reserved; enable Option 2 by raising this (RATIONALE ADR-003)
    weightLocation: '0.25',
    weightTime: '0.15',
    threshold: '0.7',
    retriever: 'bruteforce',
    locationHalfDistanceMetres: process.env.LOCATION_HALF_DISTANCE_METRES ?? '500',
  },
  // Placeholder sender; set a real verified address via SENDER_EMAIL to actually send.
  senderEmail: process.env.SENDER_EMAIL ?? 'no-reply@lostlink.example',
  // Public app URL linked in notification emails. Set once the frontend is deployed.
  cloudFrontUrl: process.env.CLOUDFRONT_URL ?? 'https://dyhlyloz80360.cloudfront.net',
};

/** Helper to build a consistent, human-readable resource name. */
export function resourceName(base: string): string {
  return `${APP_NAME}-${base}`;
}
