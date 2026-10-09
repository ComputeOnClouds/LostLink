/** Typed API boundary for the Lambda-backed LostLink HTTP API. */
import { RuntimeConfig } from './config';

export type DescriptionSource = 'user' | 'ai' | 'ai_edited' | 'unknown';

export interface ItemLocation {
  name: string;
  latitude: number;
  longitude: number;
  address?: string | null;
  provider: 'onemap' | 'manual';
  selectionMethod: 'search' | 'map';
  providerPlaceId?: string | null;
  note?: string | null;
}

export interface Report {
  itemId: string;
  type: 'lost' | 'found';
  description: string | null;
  locationZone: string | null;
  location?: ItemLocation | null;
  searchRadiusMetres?: number | null;
  eventTime: string | null;
  photoKey: string | null;
  photoUrl?: string | null;
  status: string;
  descriptionSource: DescriptionSource;
  descriptionPhotoKey?: string | null;
  descriptionGeneratedAt?: string | null;
  revision: number;
}

export interface FoundItem extends Report { organisationId: string; }

export interface MatchSuggestion {
  queryItemId: string;
  candidateItemId: string;
  organisationId: string;
  score: number;
  message: string;
}

export interface Attachment {
  attachmentId: string;
  filename: string;
  contentType: string;
  size: number;
  downloadUrl: string | null;
}

export interface ClaimMessage {
  from: 'staff' | 'claimant';
  text: string;
  at: string;
  attachments?: Attachment[];
}

export interface Claim {
  claimId: string;
  queryItemId: string;
  organisationId: string;
  state: string;
  revision: number;
  createdAt?: string;
  updatedAt?: string;
  evidenceText?: string | null;
  attachments?: Attachment[];
  item?: {
    description: string | null;
    locationZone: string | null;
    location?: ItemLocation | null;
    photoKey?: string | null;
    photoUrl?: string | null;
    status: string | null;
  } | null;
  collection?: string;
  messages?: ClaimMessage[];
}

export interface StaffClaim extends Claim {
  candidateItemId: string;
  evidenceKeys?: string[];
}

export interface ItemWrite {
  description?: string;
  locationZone?: string | null;
  location?: ItemLocation | null;
  searchRadiusMetres?: number | null;
  eventTime?: string;
  photoKey?: string | null;
  descriptionSource?: DescriptionSource;
  descriptionPhotoKey?: string | null;
  descriptionGeneratedAt?: string | null;
  revision?: number;
  confirmKeepDescription?: boolean;
}

export interface GeneratedDescription {
  description: string;
  descriptionSource: 'ai';
  descriptionPhotoKey: string;
  descriptionGeneratedAt: string;
  requestId: string;
}

interface UploadTarget { uploadUrl: string; photoKey: string; }
interface EvidenceUploadTarget {
  uploadUrl: string;
  uploadFields: Record<string, string>;
  evidenceKey: string;
  maxBytes: number;
}

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) { super(message); }
}

export class ApiClient {
  constructor(private cfg: RuntimeConfig, private token: string) {}

  private async request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    const res = await fetch(`${this.cfg.apiUrl}${path}`, {
      method,
      headers: {
        Authorization: this.token,
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal,
    });
    const text = await res.text();
    let data: Record<string, unknown> = {};
    try { data = text ? JSON.parse(text) : {}; } catch { /* no JSON body */ }
    if (!res.ok) {
      const message = res.status === 401
        ? 'Your session has expired. Sign out, then sign in again.'
        : String(data.error || `Request failed (${res.status})`);
      throw new ApiError(message, res.status);
    }
    return data as T;
  }

  searchLocations(query: string, signal?: AbortSignal): Promise<{ suggestions: ItemLocation[] }> {
    return this.request('GET', `/locations/search?q=${encodeURIComponent(query)}`, undefined, signal);
  }

  async uploadItemPhoto(kind: 'report' | 'item', file: File): Promise<string> {
    const target = await this.request<UploadTarget>(
      'POST', kind === 'report' ? '/uploads' : '/items/uploads', { contentType: file.type }
    );
    const put = await fetch(target.uploadUrl, {
      method: 'PUT', headers: { 'Content-Type': file.type }, body: file,
    });
    if (!put.ok) throw new Error(`Photo upload failed (${put.status}). Try again.`);
    return target.photoKey;
  }

  async uploadEvidence(file: File): Promise<string> {
    const target = await this.request<EvidenceUploadTarget>('POST', '/claims/uploads', {
      contentType: file.type, fileName: file.name, size: file.size,
    });
    const form = new FormData();
    Object.entries(target.uploadFields).forEach(([key, value]) => form.append(key, value));
    form.append('file', file);
    const uploaded = await fetch(target.uploadUrl, { method: 'POST', body: form });
    if (!uploaded.ok) throw new Error(`Could not upload ${file.name} (${uploaded.status}).`);
    return target.evidenceKey;
  }

  generateDescription(photoKey: string, requestId: string, itemId?: string): Promise<GeneratedDescription> {
    return this.request('POST', '/descriptions/generate', { photoKey, requestId, itemId });
  }

  listReports(): Promise<{ reports: Report[] }> { return this.request('GET', '/reports'); }
  getReport(itemId: string): Promise<Report> { return this.request('GET', `/reports/${itemId}`); }
  createReport(input: ItemWrite): Promise<{ itemId: string }> { return this.request('POST', '/reports', input); }
  updateReport(itemId: string, input: ItemWrite): Promise<Report & { rematching: boolean }> {
    return this.request('PATCH', `/reports/${itemId}`, input);
  }
  withdrawReport(itemId: string): Promise<unknown> { return this.request('DELETE', `/reports/${itemId}`); }

  listMatches(): Promise<{ matches: MatchSuggestion[] }> { return this.request('GET', '/matches'); }
  submitClaim(input: { queryItemId: string; candidateItemId: string; evidenceText: string; evidenceKeys?: string[] }) {
    return this.request<{ claimId: string; state: string }>('POST', '/claims', input);
  }
  listClaims(): Promise<{ claims: Claim[] }> { return this.request('GET', '/claims'); }
  getClaim(claimId: string): Promise<Claim> { return this.request('GET', `/claims/${claimId}`); }
  respondToClaim(claimId: string, message: string, evidenceKeys: string[], revision: number) {
    return this.request<{ state: string; revision: number }>('POST', `/claims/${claimId}/respond`, {
      message, evidenceKeys, revision,
    });
  }
  cancelClaim(claimId: string, revision?: number): Promise<{ state: string }> {
    return this.request('POST', `/claims/${claimId}/cancel`, { revision });
  }

  listItems(q?: string): Promise<{ items: FoundItem[] }> {
    return this.request('GET', `/items${q ? `?q=${encodeURIComponent(q)}` : ''}`);
  }
  getItem(itemId: string): Promise<FoundItem> { return this.request('GET', `/items/${itemId}`); }
  createItem(input: ItemWrite): Promise<{ itemId: string }> { return this.request('POST', '/items', input); }
  updateItem(itemId: string, input: ItemWrite): Promise<FoundItem & { rematching: boolean }> {
    return this.request('PATCH', `/items/${itemId}`, input);
  }
  withdrawItem(itemId: string): Promise<unknown> { return this.request('DELETE', `/items/${itemId}`); }

  listOrgClaims(): Promise<{ claims: StaffClaim[] }> { return this.request('GET', '/org/claims'); }
  getOrgClaim(claimId: string): Promise<StaffClaim> { return this.request('GET', `/org/claims/${claimId}`); }
  claimAction(
    claimId: string,
    action: 'request-info' | 'approve' | 'reject' | 'reserve' | 'handover',
    revision: number,
    message?: string
  ) {
    return this.request<{ state: string; revision: number }>(
      'POST', `/org/claims/${claimId}/${action}`, { message, revision }
    );
  }
}
