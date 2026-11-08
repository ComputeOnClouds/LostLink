import { expect, test } from '@playwright/test';
import type { Claim, MatchSuggestion, Report } from '../src/api';

const report: Report = {
  itemId: 'lost-1', type: 'lost', description: 'Black wallet', locationZone: 'library',
  eventTime: null, photoKey: null, status: 'matched', descriptionSource: 'user', revision: 1,
};
const match: MatchSuggestion = {
  queryItemId: report.itemId, candidateItemId: 'found-1', organisationId: 'org-library',
  score: 0.89, message: 'A partner organisation may have your item.',
};

test.beforeEach(async ({ page }) => {
  await page.route('**/test-api/claims', (route) => route.fulfill({ json: { claims: [] } }));
});

test('submitting a report polls through a delayed owner index and stops after completion', async ({ page }) => {
  await page.clock.install();
  let submitted = false;
  let reportReads = 0;
  let matchReads = 0;
  await page.route('**/test-api/reports', (route) => {
    if (route.request().method() === 'POST') {
      submitted = true;
      return route.fulfill({ status: 201, json: { itemId: report.itemId, status: 'pending_match' } });
    }
    if (!submitted || ++reportReads === 1) return route.fulfill({ json: { reports: [] } });
    const status = reportReads === 2 ? 'pending_match' : 'matched';
    return route.fulfill({ json: { reports: [{ ...report, status }] } });
  });
  await page.route('**/test-api/matches', (route) => {
    matchReads += 1;
    return route.fulfill({ json: { matches: reportReads >= 3 ? [match] : [] } });
  });
  await page.route('**/test-api/locations/search?**', (route) => route.fulfill({ json: { suggestions: [
    { name: 'Central Library', latitude: 1.2966, longitude: 103.7736, provider: 'onemap', selectionMethod: 'search' },
  ] } }));
  await page.route('https://www.onemap.gov.sg/maps/tiles/**', (route) => route.abort());
  await page.goto('/tests/individual-portal.html');
  await expect(page.getByText('No reports yet.', { exact: false })).toBeVisible();
  await page.getByLabel(/Description/).fill(report.description!);
  await page.getByRole('combobox', { name: /Where did you lose it/ }).fill('Library');
  await page.getByRole('option', { name: /Central Library/ }).click();
  await page.getByRole('button', { name: 'Submit report' }).click();
  await expect(page.getByText('Report submitted.', { exact: false })).toBeVisible();
  await expect.poll(() => reportReads).toBe(1);

  await page.clock.fastForward(4_000);
  await expect(page.getByText('searching…', { exact: true })).toBeVisible();
  await page.clock.fastForward(4_000);
  await expect(page.getByText('match found', { exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: report.description! }).getByText('89% similarity')).toBeVisible();
  const completedMatchReads = matchReads;
  await page.clock.runFor(12_000);
  expect(reportReads).toBe(3);
  expect(matchReads).toBe(completedMatchReads);
});

test('manual refresh recovers from failure and preserves the right draft when a suggestion disappears', async ({ page }) => {
  const otherReport = { ...report, itemId: 'lost-2', description: 'Leather card holder' };
  const otherMatch = { ...match, queryItemId: otherReport.itemId };
  let suggestions = [match, otherMatch];
  let failed = false;
  await page.route('**/test-api/reports', (route) => route.fulfill({ json: { reports: [report, otherReport] } }));
  await page.route('**/test-api/matches', (route) => failed
    ? route.fulfill({ status: 503, json: { error: 'Temporarily unavailable.' } })
    : route.fulfill({ json: { matches: suggestions } }));
  await page.goto('/tests/individual-portal.html');

  const wallet = page.getByRole('region', { name: report.description! });
  await wallet.getByRole('button', { name: /submit a claim/ }).click();
  const evidence = wallet.getByLabel('Proof of ownership');
  await evidence.fill('Red stripe on the inside');
  await expect(page.getByLabel('Proof of ownership')).toHaveCount(1);
  const refresh = page.getByRole('button', { name: 'Refresh results' });

  failed = true;
  await refresh.click();
  await expect(page.getByRole('alert')).toContainText('Temporarily unavailable.');
  await expect(evidence).toHaveValue('Red stripe on the inside');

  failed = false;
  suggestions = [otherMatch];
  await refresh.click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(wallet.getByRole('button', { name: 'Submit claim', exact: true })).toBeDisabled();
  await expect(evidence).toHaveValue('Red stripe on the inside');

  suggestions = [match, otherMatch];
  await refresh.click();
  await expect(wallet.getByRole('button', { name: 'Submit claim', exact: true })).toBeEnabled();
  await expect(evidence).toHaveValue('Red stripe on the inside');
});

test('editing matching inputs polls even if the owner index still shows the old revision', async ({ page }) => {
  await page.clock.install();
  const updated = { ...report, description: 'Brown wallet', revision: 2 };
  let saved = false;
  let readsAfterSave = 0;
  await page.route('**/test-api/reports', (route) => {
    const listed = saved && ++readsAfterSave >= 2 ? { ...updated, status: 'no_match' } : report;
    return route.fulfill({ json: { reports: [listed] } });
  });
  await page.route(`**/test-api/reports/${report.itemId}`, (route) => {
    if (route.request().method() === 'GET') return route.fulfill({ json: report });
    saved = true;
    return route.fulfill({ json: { ...updated, status: 'pending_match', rematching: true } });
  });
  await page.route('**/test-api/matches', (route) => route.fulfill({
    json: { matches: readsAfterSave >= 2 ? [] : [match] },
  }));
  await page.goto('/tests/individual-portal.html');
  await expect(page.getByText('89% similarity')).toBeVisible();
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  const editor = page.locator('.tile').filter({ has: page.getByRole('button', { name: 'Save changes' }) });
  await editor.getByLabel(/Description/).fill(updated.description);
  await editor.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByText('We’re checking matches again.', { exact: false })).toBeVisible();
  await expect.poll(() => readsAfterSave).toBe(1);

  await page.clock.fastForward(4_000);
  await expect(page.getByText('no match yet', { exact: true })).toBeVisible();
  await expect(page.getByText('89% similarity')).toHaveCount(0);
});

test('a submitted claim removes only its match even while the API still returns the old suggestion', async ({ page }) => {
  const otherReport = { ...report, itemId: 'lost-2', description: 'Leather card holder' };
  const otherMatch = { ...match, queryItemId: otherReport.itemId };
  let claims: Claim[] = [];
  let listedClaims: Claim[] = [];
  await page.route('**/test-api/reports', (route) => route.fulfill({ json: { reports: [report, otherReport] } }));
  await page.route('**/test-api/matches', (route) => route.fulfill({ json: { matches: [match, otherMatch] } }));
  await page.route('**/test-api/claims', (route) => {
    if (route.request().method() === 'POST') {
      const input = route.request().postDataJSON();
      const claim: Claim = {
        claimId: `claim-${claims.length + 1}`, queryItemId: input.queryItemId,
        organisationId: match.organisationId, state: 'submitted', revision: 1,
        evidenceText: input.evidenceText, attachments: [], messages: [], item: null,
        createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(),
      };
      claims = [...claims, claim];
      return route.fulfill({ status: 201, json: { claimId: claim.claimId, state: claim.state } });
    }
    return route.fulfill({ json: { claims: listedClaims } });
  });
  await page.route('**/test-api/claims/claim-*', (route) => {
    const claimId = new URL(route.request().url()).pathname.split('/').pop();
    const claim = claims.find((item) => item.claimId === claimId);
    return claim
      ? route.fulfill({ json: claim })
      : route.fulfill({ status: 404, json: { error: 'Claim not found.' } });
  });
  await page.route('**/test-api/claims/claim-*/cancel', (route) => {
    const claimId = new URL(route.request().url()).pathname.split('/').at(-2);
    claims = claims.map((claim) => claim.claimId === claimId
      ? { ...claim, state: 'cancelled', revision: claim.revision + 1 } : claim);
    return route.fulfill({ json: { state: 'cancelled' } });
  });
  await page.goto('/tests/individual-portal.html');
  await expect(page.getByText('No claims yet.', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'View claim' })).toHaveCount(0);
  const wallet = page.getByRole('region', { name: report.description! });
  await wallet.getByRole('button', { name: /submit a claim/ }).click();
  await wallet.getByLabel('Proof of ownership').fill('Red stripe on the inside');
  const submission = page.waitForRequest((request) => request.url().endsWith('/test-api/claims') && request.method() === 'POST');
  await wallet.getByRole('button', { name: 'Submit claim', exact: true }).click();
  expect((await submission).postDataJSON()).toMatchObject({
    queryItemId: report.itemId, candidateItemId: match.candidateItemId, evidenceText: 'Red stripe on the inside',
  });

  await expect(wallet).toHaveCount(0);
  await expect(page.getByRole('region', { name: otherReport.description })).toBeVisible();
  await expect(page.getByRole('button', { name: 'View claim' })).toHaveCount(1);
  await page.getByRole('button', { name: 'View claim' }).click();
  const details = page.getByRole('dialog', { name: 'Claim details' });
  await expect(details.getByText('Red stripe on the inside', { exact: true })).toBeVisible();
  await expect(details.getByText('Awaiting staff review.', { exact: true })).toBeVisible();
  await details.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(details).toHaveCount(0);

  const refreshed = page.waitForResponse('**/test-api/matches');
  await page.getByRole('button', { name: 'Refresh results' }).click();
  await refreshed;
  await expect(wallet).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'View claim', exact: true })).toHaveCount(1);

  // The owner index eventually includes the claim, without creating a second card.
  listedClaims = claims.map((claim) => ({ ...claim }));
  const caughtUp = page.waitForResponse('**/test-api/claims');
  await page.getByRole('button', { name: 'Refresh results' }).click();
  await caughtUp;
  await expect(page.getByRole('button', { name: 'View claim', exact: true })).toHaveCount(1);

  // A stale submitted revision must not undo a locally confirmed cancellation.
  await page.getByRole('button', { name: 'Cancel claim', exact: true }).click();
  await expect(page.getByText('cancelled', { exact: true })).toBeVisible();
  const staleRefresh = page.waitForResponse('**/test-api/claims');
  await page.getByRole('button', { name: 'Refresh results' }).click();
  await staleRefresh;
  await expect(page.getByText('cancelled', { exact: true })).toBeVisible();
  await expect(wallet).toHaveCount(0);
});

test('polling skips hidden pages, expires and refreshes once when the page becomes visible', async ({ page }) => {
  await page.clock.install();
  await page.addInitScript(() => {
    Object.defineProperty(document, 'hidden', { value: false, configurable: true });
  });
  let reads = 0;
  await page.route('**/test-api/reports', (route) => {
    reads += 1;
    return route.fulfill({ json: { reports: [{ ...report, status: 'pending_match' }] } });
  });
  await page.route('**/test-api/matches', (route) => route.fulfill({ json: { matches: [] } }));
  await page.goto('/tests/individual-portal.html');
  await expect(page.getByText('No potential matches yet.', { exact: false })).toBeVisible();
  const initialReads = reads;

  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { value: true, configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.clock.runFor(65_000);
  expect(reads).toBe(initialReads);

  const resumed = page.waitForResponse('**/test-api/matches');
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { value: false, configurable: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await resumed;
  await page.clock.runFor(8_000);
  expect(reads).toBe(initialReads + 1);
});
