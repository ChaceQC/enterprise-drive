import { expect, test } from '@playwright/test'

import { installMockApi } from './mock-api'

test.beforeEach(async ({ page }) => {
  await installMockApi(page)
})

test('搜索、回收站、分享与通知流程', async ({ page }) => {
  await page.goto('/search')
  await page.getByLabel('搜索关键词').fill('发布')
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await expect(page.getByText('发布说明.pdf')).toBeVisible()

  await page.getByRole('link', { name: '回收站' }).click()
  await expect(page.getByText('旧方案.docx')).toBeVisible()
  await page.getByLabel('选择 旧方案.docx').check()
  await page.getByRole('button', { name: '恢复', exact: true }).click()

  await page.getByRole('link', { name: '分享' }).click()
  await expect(page.getByText('发布说明.pdf')).toBeVisible()
  await page.getByRole('link', { name: '通知' }).click()
  await expect(page.getByText(/协作者 分享了/)).toBeVisible()
  await page.getByRole('button', { name: '标记已读' }).click()
})

test('管理员概览与审计页面', async ({ page }) => {
  await page.goto('/admin')
  await expect(page.getByText('活跃用户')).toBeVisible()
  await page.getByRole('link', { name: '用户' }).click()
  await expect(page.getByRole('cell', { name: '系统管理员 admin' })).toBeVisible()
  await page.getByRole('link', { name: '审计' }).click()
  await expect(page.getByText('file.downloaded')).toBeVisible()
})
