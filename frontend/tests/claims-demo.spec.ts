import { expect, test } from '@playwright/test';

for (const decision of ['reject', 'handover']) {
  test(`manual demo preserves a ${decision} decision across reload and hides its suggestion`, async ({ page }) => {
    await page.clock.install();
    await page.goto('/tests/claims-demo.html');
    const wallet = page.getByRole('region', { name: 'Black wallet', exact: true });
    await expect(wallet).toBeVisible();
    await page.clock.fastForward(8_000);
    await expect(page.getByRole('region', { name: 'iPhone with a pink case', exact: true })).toBeVisible();

    await wallet.getByRole('button', { name: /submit a claim/ }).click();
    await wallet.getByLabel('Proof of ownership').fill('Red stripe on the inside');
    await wallet.getByRole('button', { name: 'Submit claim', exact: true }).click();
    await expect(wallet).toHaveCount(0);
    await page.getByRole('button', { name: 'View claim', exact: true }).click();
    const details = page.getByRole('dialog', { name: 'Claim details' });
    await expect(details.getByText('Red stripe on the inside', { exact: true })).toBeVisible();
    await expect(details.getByRole('heading', { name: 'Verified item' })).toHaveCount(0);
    await details.getByRole('button', { name: 'Close', exact: true }).click();

    await page.getByRole('button', { name: '工作人员视角', exact: true }).click();
    await page.getByRole('button', { name: 'View claim', exact: true }).click();
    if (decision === 'reject') {
      await details.getByRole('button', { name: 'Reject claim', exact: true }).click();
      await expect(details.getByText('rejected', { exact: true })).toBeVisible();
    } else {
      await details.getByRole('button', { name: 'Approve ownership', exact: true }).click();
      await details.getByRole('button', { name: 'Reserve for collection', exact: true }).click();
      await details.getByRole('button', { name: 'Record handover', exact: true }).click();
      await expect(details.getByText('handed over', { exact: true })).toBeVisible();
    }
    await details.getByRole('button', { name: 'Close', exact: true }).click();
    await page.reload();
    await expect(wallet).toHaveCount(0);
    await expect(page.getByRole('region', { name: 'iPhone with a pink case', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'View claim', exact: true }).click();
    await expect(details.getByText('Red stripe on the inside', { exact: true })).toBeVisible();
    await expect(details.getByRole('heading', { name: 'Verified item' })).toHaveCount(decision === 'reject' ? 0 : 1);
  });
}
