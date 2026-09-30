/**
 * API client — the single clean layer between the UI and the backend (RATIONALE ADR-008).
 *
 * Every call attaches the Cognito ID token. Endpoint shapes live here only, so route
 * changes don't ripple through components.
 */
import { RuntimeConfig } from './config';

/** An individual's lost report, as returned by the reports API. */
export interface Report {
  itemId: string;
  type: string; // "lost"
  description: string | null;
  locationZone: string | null;
  eventTime: string | null; // ISO 8601
  photoKey: string | null; // S3 key, if a photo was attached
  status: string; // pending_match | withdrawn | ...
}

/** A staff-registered found item (a Report plus the owning organisation). */
export interface FoundItem extends Report {
  organisationId: string;
}

/**
 * A potential match shown to the individual. Deliberately carries NO description or
 * photo of the found item — only the org and a confidence score — so item details stay
 * hidden until a claim is approved (the privacy core, RATIONALE ADR-022).
 */
export interface MatchSuggestion {
  queryItemId: string; // the individual's lost report
  candidateItemId: string; // opaque handle used to submit a claim
  organisationId: string; // which partner org may hold it
  score: number; // 0..1 blended match confidence
  message: string;
}

/** A claim as the individual sees it. ``item`` is populated only once approved. */
export interface Claim {
  claimId: string;
  queryItemId: string;
  organisationId: string;
  state: string; // submitted | info_requested | approved | rejected | reserved | handed_over | cancelled
  createdAt?: string;
  updatedAt?: string;
  // Found-item details — null until staff approve the claim (privacy gate).
  item?: { description: string | null; locationZone: string | null; status: string | null } | null;
  collection?: string; // collection instructions, shown once approved
  messages?: Array<{ from: string; text: string; at: string }>; // Q&A thread
}

/** Result of requesting a presigned upload: PUT here, then reference photoKey. */
export interface UploadTarget {
  uploadUrl: string;
  photoKey: string;
}

export class ApiClient {
  // `token` is the Cognito ID token; attached to every request as the Authorization
  // header so API Gateway's JWT authorizer can validate the caller.
  constructor(private cfg: RuntimeConfig, private token: string) {}

  /** Core fetch wrapper: attaches auth, parses JSON, throws on non-2xx with the API's error. */
  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await fetch(`${this.cfg.apiUrl}${path}`, {
      method,
      headers: {
        Authorization: this.token,
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    const text = await res.text();
    const data = text ? JSON.parse(text) : {};
    if (!res.ok) {
      throw new Error(data.error || `Request failed (${res.status})`);
    }
    return data as T;
  }

  /** Upload a photo via a presigned PUT and return the stored photo key. */
  private async uploadPhoto(uploadPath: string, file: File): Promise<string> {
    const target = await this.request<UploadTarget>('POST', uploadPath, {
      contentType: file.type,
    });
    const put = await fetch(target.uploadUrl, {
      method: 'PUT',
      headers: { 'Content-Type': file.type },
      body: file,
    });
    if (!put.ok) throw new Error(`Photo upload failed (${put.status})`);
    return target.photoKey;
  }

  // ---- Individual (reports) --------------------------------------------------------

  /** List the signed-in individual's own lost reports. */
  listReports(): Promise<{ reports: Report[] }> {
    return this.request('GET', '/reports');
  }

  /** Create a lost report; uploads the photo first (if any) and passes its key. */
  async createReport(input: {
    description?: string;
    locationZone: string;
    eventTime?: string;
    photo?: File | null;
  }): Promise<{ itemId: string }> {
    let photoKey: string | undefined;
    if (input.photo) {
      photoKey = await this.uploadPhoto('/uploads', input.photo);
    }
    return this.request('POST', '/reports', {
      description: input.description,
      locationZone: input.locationZone,
      eventTime: input.eventTime,
      photoKey,
    });
  }

  withdrawReport(itemId: string): Promise<unknown> {
    return this.request('DELETE', `/reports/${itemId}`);
  }

  // ---- Individual (claims) ---------------------------------------------------------

  /** Potential matches against the caller's reports (item details hidden). */
  listMatches(): Promise<{ matches: MatchSuggestion[] }> {
    return this.request('GET', '/matches');
  }

  /** Submit an ownership claim (with evidence text) against a surfaced match. */
  submitClaim(input: {
    queryItemId: string;
    candidateItemId: string;
    evidenceText: string;
  }): Promise<{ claimId: string; state: string }> {
    return this.request('POST', '/claims', input);
  }

  listClaims(): Promise<{ claims: Claim[] }> {
    return this.request('GET', '/claims');
  }

  getClaim(claimId: string): Promise<Claim> {
    return this.request('GET', `/claims/${claimId}`);
  }

  cancelClaim(claimId: string): Promise<{ state: string }> {
    return this.request('POST', `/claims/${claimId}/cancel`, {});
  }

  // ---- Staff (inventory) -----------------------------------------------------------

  listItems(q?: string): Promise<{ items: FoundItem[] }> {
    const qs = q ? `?q=${encodeURIComponent(q)}` : '';
    return this.request('GET', `/items${qs}`);
  }

  async createItem(input: {
    description?: string;
    locationZone: string;
    eventTime?: string;
    photo?: File | null;
  }): Promise<{ itemId: string }> {
    let photoKey: string | undefined;
    if (input.photo) {
      photoKey = await this.uploadPhoto('/items/uploads', input.photo);
    }
    return this.request('POST', '/items', {
      description: input.description,
      locationZone: input.locationZone,
      eventTime: input.eventTime,
      photoKey,
    });
  }

  withdrawItem(itemId: string): Promise<unknown> {
    return this.request('DELETE', `/items/${itemId}`);
  }

  // ---- Staff (claim review) --------------------------------------------------------

  /** Claims against the staff member's organisation (full evidence visible to staff). */
  listOrgClaims(): Promise<{ claims: StaffClaim[] }> {
    return this.request('GET', '/org/claims');
  }

  /** Advance a claim through the staff-side state machine (request-info/approve/etc.). */
  claimAction(
    claimId: string,
    action: 'request-info' | 'approve' | 'reject' | 'reserve' | 'handover',
    message?: string
  ): Promise<{ state: string }> {
    return this.request('POST', `/org/claims/${claimId}/${action}`, message ? { message } : {});
  }
}

/**
 * A claim as STAFF see it. Unlike the individual's Claim view, staff always see the
 * claimant's evidence (text + uploaded file keys) because it is a claim against their own
 * organisation — that is what they review to verify ownership.
 */
export interface StaffClaim {
  claimId: string;
  queryItemId: string;
  candidateItemId: string;
  organisationId: string;
  state: string;
  evidenceText: string | null;
  evidenceKeys: string[]; // S3 keys of uploaded evidence files
  createdAt?: string;
  updatedAt?: string;
}
