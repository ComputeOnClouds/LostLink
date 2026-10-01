/**
 * Human-readable labels for the backend status/state strings. The CSS badge class still
 * uses the raw status value (e.g. `badge no_match`); only the displayed TEXT is friendly.
 */

// Lost-report status (set by the matching worker).
const REPORT_STATUS: Record<string, string> = {
  pending_match: 'searching…',
  matched: 'match found',
  no_match: 'no match yet',
  withdrawn: 'withdrawn',
};

// Found-item status (staff + claims driven).
const ITEM_STATUS: Record<string, string> = {
  available: 'available',
  reserved: 'reserved',
  closed: 'closed',
  withdrawn: 'withdrawn',
};

// Claim state (7-state machine).
const CLAIM_STATE: Record<string, string> = {
  submitted: 'submitted',
  info_requested: 'info requested',
  approved: 'approved',
  rejected: 'rejected',
  reserved: 'reserved',
  handed_over: 'handed over',
  cancelled: 'cancelled',
};

const nice = (s: string) => s.replace(/_/g, ' ');

export const reportStatusLabel = (s: string) => REPORT_STATUS[s] ?? nice(s);
export const itemStatusLabel = (s: string) => ITEM_STATUS[s] ?? nice(s);
export const claimStateLabel = (s: string) => CLAIM_STATE[s] ?? nice(s);
