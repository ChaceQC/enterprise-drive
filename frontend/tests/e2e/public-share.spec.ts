import { expect, test } from '@playwright/test'

import { installMockApi } from './mock-api'

test('外链提取码页面不依赖登录态', async ({ page }) => {
  await installMockApi(page, { authenticated: false })
  await page.route('**/api/v1/public/shares/access', async (route) => {
    await route.fulfill({
      body: JSON.stringify({
        download_count: 0,
        expires_at: null,
        item_node_ids: ['22222222-2222-4222-8222-222222222222'],
        max_downloads: 10,
        max_views: 20,
        permission: 'download',
        root_node_id: '22222222-2222-4222-8222-222222222222',
        share_id: '66666666-6666-4666-8666-666666666666',
        view_count: 1,
      }),
      contentType: 'application/json',
      status: 200,
    })
  })
  await page.goto('/public-share?tenant=default&token=token-e2e')
  await page.getByLabel('提取码（如有）').fill('1234')
  await page.getByRole('button', { name: '验证并查看' }).click()
  await expect(page.getByText('访问已验证')).toBeVisible()
  await expect(page.getByRole('button', { name: '下载' })).toBeVisible()
})
