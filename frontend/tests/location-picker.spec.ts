import { expect, test } from '@playwright/test';

const library = { name: 'Central Library', address: 'NUS, 12 Kent Ridge Crescent', latitude: 1.2966, longitude: 103.7736, provider: 'onemap', selectionMethod: 'search' };

test.beforeEach(async ({ page }) => {
  // Tests exercise component behavior, not the availability of OneMap's tile server.
  await page.route('https://www.onemap.gov.sg/maps/tiles/**', (route) => route.abort());
  await page.route('**/test-api/locations/search?**', (route) => route.fulfill({ json: { suggestions: [library] } }));
  await page.route('**/test-api/save', (route) => route.fulfill({ json: {} }));
});

test('keyboard selection fills coordinates and saving resets the picker', async ({ page }) => {
  await page.goto('/tests/location-picker.html');
  await page.getByLabel(/Description/).fill('Black wallet');
  const search = page.getByRole('combobox', { name: 'Where did you lose it?*' });
  await search.fill('Central');
  await expect(page.getByRole('listbox').getByRole('option')).toBeVisible();
  await search.press('ArrowDown');
  await search.press('Enter');
  await expect(search).toHaveValue(library.name);
  await expect(page.locator('.location-pin')).toBeVisible();
  await page.getByLabel('Search within').selectOption('1000');
  const request = page.waitForRequest('**/test-api/save');
  await page.getByRole('button', { name: 'Save item' }).click();
  const payload = (await request).postDataJSON();
  expect(payload.location.latitude).toBe(library.latitude);
  expect(payload.location.longitude).toBe(library.longitude);
  expect(payload.searchRadiusMetres).toBe(1000);
  await expect(search).toHaveValue('');
});

test('changing selected text clears stale coordinates and cannot save', async ({ page }) => {
  await page.goto('/tests/location-picker.html');
  await page.getByLabel(/Description/).fill('Black wallet');
  const search = page.getByRole('combobox', { name: /Where/ });
  await search.fill('Library');
  await page.getByRole('listbox').getByRole('option').click();
  await search.fill('Another place');
  await page.getByRole('button', { name: 'Save item' }).click();
  await expect(page.getByRole('alert')).toContainText('Choose a location suggestion');
  await expect(page.locator('.location-pin')).toHaveCount(0);
});

test('manual coordinates work when search is unavailable, with mobile layout', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('**/test-api/locations/search?**', (route) => route.fulfill({ status: 503, json: { error: 'Place search is unavailable. Choose on the map or try again.' } }));
  await page.goto('/tests/location-picker.html?kind=item');
  await page.getByLabel(/Description/).fill('Found wallet');
  const search = page.getByRole('combobox', { name: /Where/ });
  await search.fill('Library entrance');
  await expect(page.getByText('Place search is unavailable.', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Choose on map' }).click();
  await page.getByText('Enter coordinates instead', { exact: true }).click();
  await page.getByLabel('Latitude', { exact: true }).fill('51');
  await page.getByLabel('Longitude', { exact: true }).fill('103.8');
  await page.getByRole('button', { name: 'Set location pin' }).click();
  await expect(page.getByRole('alert')).toContainText('Singapore service area');
  await page.getByLabel('Latitude', { exact: true }).fill('1.2966');
  await page.getByLabel('Longitude', { exact: true }).fill('103.7736');
  await page.getByRole('button', { name: 'Set location pin' }).click();
  await page.getByLabel(/Landmark or floor/).fill('Near the entrance');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const request = page.waitForRequest('**/test-api/save');
  await page.getByRole('button', { name: 'Save item' }).click();
  const payload = (await request).postDataJSON();
  expect(payload.location.selectionMethod).toBe('map');
  expect(payload.location.note).toBe('Near the entrance');
  expect(payload).not.toHaveProperty('searchRadiusMetres');
});

test('late search responses cannot replace the current query', async ({ page }) => {
  await page.route('**/test-api/locations/search?**', async (route) => {
    const query = new URL(route.request().url()).searchParams.get('q');
    if (query === 'Library') await new Promise((resolve) => setTimeout(resolve, 800));
    await route.fulfill({ json: { suggestions: [{ ...library, name: query }] } });
  });
  await page.goto('/tests/location-picker.html');
  const search = page.getByRole('combobox', { name: /Where/ });
  await search.fill('Library');
  await page.waitForRequest('**/test-api/locations/search?q=Library');
  await search.fill('Park');
  await expect(page.getByRole('listbox').getByRole('option')).toContainText('Park');
  await page.waitForTimeout(900);
  await expect(page.getByRole('listbox').getByRole('option')).toContainText('Park');
});

test('legacy records save without inventing coordinates', async ({ page }) => {
  await page.goto('/tests/location-picker.html?legacy');
  await expect(page.getByText('Saved legacy location:', { exact: false })).toContainText('zone-library');
  const request = page.waitForRequest('**/test-api/save');
  await page.getByRole('button', { name: 'Save item' }).click();
  const payload = (await request).postDataJSON();
  expect(payload.location).toBeNull();
  expect(payload.locationZone).toBe('zone-library');
});

test('moving a selected pin clears its address and mobile zoom targets remain 44 px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/tests/location-picker.html');
  await page.getByLabel(/Description/).fill('Black wallet');
  await page.getByRole('combobox', { name: /Where/ }).fill('Library');
  await page.getByRole('listbox').getByRole('option').click();
  await expect(page.locator('.location-pin')).toBeVisible();
  const zoom = await page.locator('.leaflet-control-zoom-in').boundingBox();
  expect(zoom?.width).toBe(44);
  expect(zoom?.height).toBe(44);
  await page.locator('.location-map').click({ position: { x: 220, y: 180 } });
  const request = page.waitForRequest('**/test-api/save');
  await page.getByRole('button', { name: 'Save item' }).click();
  const payload = (await request).postDataJSON();
  expect(payload.location.selectionMethod).toBe('map');
  expect(payload.location.address).toBeNull();
  expect(payload.location.name).toBe(library.name);
});
