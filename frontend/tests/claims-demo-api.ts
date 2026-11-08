import { ApiClient, ApiError, Claim, MatchSuggestion, Report, StaffClaim } from '../src/api';

const STORAGE_KEY = 'lostlink-claims-demo-v1';
export const DEMO_CHANGE = 'lostlink-claims-demo-change';
interface DemoState { claims: StaffClaim[]; matchingCompletesAt: number; }

const reports: Report[] = ['Black wallet', 'iPhone with a pink case'].map((description, index) => ({
  itemId: `lost-${index + 1}`, type: 'lost', description, locationZone: 'Central Library',
  eventTime: null, photoKey: null, status: 'matched', descriptionSource: 'user', revision: 1,
}));
const suggestions: MatchSuggestion[] = reports.map((report, index) => ({
  queryItemId: report.itemId, candidateItemId: `found-${index + 1}`, organisationId: 'org-library',
  score: index === 0 ? 0.89 : 0.91, message: 'A partner organisation may be holding an item matching this report.',
}));
const transitions: Record<string, { from: string[]; to: string }> = {
  'request-info': { from: ['submitted'], to: 'info_requested' },
  approve: { from: ['submitted'], to: 'approved' },
  reject: { from: ['submitted', 'info_requested'], to: 'rejected' },
  reserve: { from: ['approved'], to: 'reserved' },
  handover: { from: ['approved', 'reserved'], to: 'handed_over' },
  respond: { from: ['info_requested'], to: 'submitted' },
  cancel: { from: ['submitted', 'info_requested'], to: 'cancelled' },
};

export function readDemoState(): DemoState {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) return JSON.parse(saved) as DemoState;
  const initial = { claims: [], matchingCompletesAt: Date.now() + 6_000 };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(initial));
  return initial;
}

function save(state: DemoState) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  window.dispatchEvent(new Event(DEMO_CHANGE));
}

export function resetDemo() {
  localStorage.removeItem(STORAGE_KEY);
  readDemoState();
}

// A browser-only adapter for manual UI exploration. Production uses the AWS ApiClient.
export class DemoApi extends ApiClient {
  constructor() {
    super({ apiUrl: '/unused-demo-api', region: 'demo', userPoolId: 'demo', userPoolClientId: 'demo' }, 'demo');
  }

  override async listReports() {
    const state = readDemoState();
    return { reports: reports.map((report, index) => ({
      ...report, status: index === 1 && Date.now() < state.matchingCompletesAt ? 'pending_match' : 'matched',
    })) };
  }

  override async listMatches() {
    const state = readDemoState();
    return { matches: suggestions.filter((match, index) =>
      (index === 0 || Date.now() >= state.matchingCompletesAt)
      && !state.claims.some((claim) => claim.queryItemId === match.queryItemId && claim.candidateItemId === match.candidateItemId)) };
  }

  override async submitClaim(input: { queryItemId: string; candidateItemId: string; evidenceText: string; evidenceKeys?: string[] }) {
    const state = readDemoState();
    if (state.claims.some((claim) => claim.queryItemId === input.queryItemId && claim.candidateItemId === input.candidateItemId)) {
      throw new ApiError('You already submitted a claim for this match. View it in My claims.', 409);
    }
    if (!input.evidenceText.trim()) throw new ApiError('Enter your proof of ownership.', 400);
    const now = new Date().toISOString();
    const claim: StaffClaim = {
      claimId: crypto.randomUUID(), queryItemId: input.queryItemId, candidateItemId: input.candidateItemId,
      organisationId: 'org-library', state: 'submitted', revision: 1, evidenceText: input.evidenceText,
      messages: [], attachments: [], createdAt: now, updatedAt: now,
    };
    save({ ...state, claims: [...state.claims, claim] });
    return { claimId: claim.claimId, state: claim.state };
  }

  private find(claimId: string) {
    const claim = readDemoState().claims.find((item) => item.claimId === claimId);
    if (!claim) throw new ApiError('Claim not found.', 404);
    return claim;
  }

  private view(claim: StaffClaim, staff = false): Claim {
    const visible = staff || ['approved', 'reserved', 'handed_over'].includes(claim.state);
    return {
      ...claim,
      item: visible ? {
        description: claim.candidateItemId === 'found-1' ? 'Black wallet with a red stripe inside' : 'iPhone with a pink heart-pattern case',
        locationZone: 'Central Library service desk',
        status: claim.state === 'handed_over' ? 'closed' : claim.state === 'reserved' ? 'reserved' : 'available',
      } : null,
      collection: visible ? 'Collect from the Central Library service desk.' : undefined,
    };
  }

  override async listClaims() { return { claims: readDemoState().claims.map((claim) => this.view(claim)) }; }
  override async getClaim(claimId: string) { return this.view(this.find(claimId)); }
  override async listOrgClaims() { return { claims: readDemoState().claims }; }
  override async getOrgClaim(claimId: string): Promise<StaffClaim> {
    const claim = this.find(claimId);
    return { ...claim, ...this.view(claim, true) };
  }

  private transition(claimId: string, action: string, revision?: number, message?: string) {
    const state = readDemoState();
    const claim = this.find(claimId);
    const rule = transitions[action];
    if (!rule?.from.includes(claim.state) || (revision !== undefined && revision !== claim.revision)) {
      throw new ApiError('This claim changed. Reopen it to review the latest state.', 409);
    }
    const at = new Date().toISOString();
    const updated: StaffClaim = {
      ...claim, state: rule.to, revision: claim.revision + 1, updatedAt: at,
      messages: message ? [...(claim.messages ?? []), {
        from: action === 'respond' ? 'claimant' : 'staff', text: message, at,
      }] : claim.messages,
    };
    save({ ...state, claims: state.claims.map((item) => item.claimId === claimId ? updated : item) });
    return { state: updated.state, revision: updated.revision };
  }

  override async claimAction(claimId: string, action: 'request-info' | 'approve' | 'reject' | 'reserve' | 'handover', revision: number, message?: string) {
    return this.transition(claimId, action, revision, message);
  }
  override async cancelClaim(claimId: string, revision?: number) { return this.transition(claimId, 'cancel', revision); }
  override async respondToClaim(claimId: string, message: string, _keys: string[] = [], revision?: number) {
    return this.transition(claimId, 'respond', revision, message);
  }
  override async uploadEvidence(_file: File): Promise<string> {
    throw new ApiError('Use text evidence in this local demo.', 400);
  }
}
