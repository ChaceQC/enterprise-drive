import { expect, test } from '@playwright/test'

import { installMockApi } from './mock-api'

test('管理员查看 Sprint 12 治理看板与受控重放入口', async ({ page }) => {
  await installMockApi(page)
  await page.goto('/admin/governance')

  await expect(page.getByRole('heading', { name: '管理后台' })).toBeVisible()
  await expect(page.getByRole('link', { name: '治理看板' })).toHaveClass(/active/)

  const summary = page.getByRole('region', { name: '治理摘要' })
  await expect(summary.getByText('Outbox dead-letter')).toBeVisible()
  await expect(summary.getByText('大目录后台任务')).toBeVisible()
  await expect(summary.getByText('权限重算', { exact: true })).toBeVisible()
  await expect(summary.getByText('活跃治理告警')).toBeVisible()

  await expect(page.getByRole('heading', { name: '治理告警' })).toBeVisible()
  await expect(page.getByText('Outbox 存在 1 个 dead 事件')).toBeVisible()

  const taskPanel = page.locator('.governance-panel').filter({
    has: page.getByRole('heading', {
      exact: true,
      name: '大目录任务与权限重算',
    }),
  })
  await expect(taskPanel.getByText('删除', { exact: true })).toBeVisible()
  await expect(taskPanel.getByText('4200 / 10000', { exact: true })).toBeVisible()
  await expect(taskPanel.getByText('OPENSEARCH_UNAVAILABLE')).toBeVisible()
  await taskPanel.getByRole('button', { name: '重试' }).click()
  await expect(taskPanel.getByText('OPENSEARCH_UNAVAILABLE')).toHaveCount(0)
  await expect(
    taskPanel.getByRole('cell', { exact: true, name: 'pending' }),
  ).toBeVisible()

  const lifecyclePanel = page.locator('.governance-panel').filter({
    has: page.getByRole('heading', {
      exact: true,
      name: '生命周期策略与运行',
    }),
  })
  await expect(
    lifecyclePanel.getByRole('cell', { exact: true, name: '正式执行' }),
  ).toBeVisible()
  await lifecyclePanel.getByRole('button', { name: 'Dry-run' }).click()
  await expect(
    lifecyclePanel.getByRole('cell', { exact: true, name: 'Dry-run' }),
  ).toBeVisible()
  await expect(
    lifecyclePanel.getByRole('cell', { exact: true, name: 'pending' }),
  ).toBeVisible()

  const auditPanel = page.locator('.governance-panel').filter({
    has: page.getByRole('heading', {
      exact: true,
      name: '审计归档与投递',
    }),
  })
  await expect(auditPanel.getByText('12 个', { exact: true })).toBeVisible()
  await expect(auditPanel.getByText('audit-2026-07.jsonl.gz')).toBeVisible()
  await expect(auditPanel.getByText(/Ed25519/)).toBeVisible()

  const deadLetterPanel = page.locator('.governance-panel').filter({
    has: page.getByRole('heading', {
      exact: true,
      name: 'Outbox dead-letter',
    }),
  })
  await expect(
    deadLetterPanel.getByText('search.index_requested'),
  ).toBeVisible()
  await expect(
    deadLetterPanel.getByText('OPENSEARCH_UNAVAILABLE'),
  ).toBeVisible()
  await deadLetterPanel.getByRole('button', { name: '重放' }).click()
  await expect(
    deadLetterPanel.getByText('事件已重新进入投递队列。'),
  ).toBeVisible()
  await expect(
    deadLetterPanel.getByText('search.index_requested'),
  ).toHaveCount(0)
})
