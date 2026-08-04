import { expect, test } from '@playwright/test'

import { installMockApi } from './mock-api'

test('登录、文件批量操作与上传队列', async ({ page }) => {
  await installMockApi(page, { authenticated: false })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()

  await page.getByLabel('用户名').fill('admin')
  await page.getByLabel('密码').fill('admin-password')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '我的文件' })).toBeVisible()

  await page.getByLabel('文件版本').click()
  const versionDialog = page.getByRole('dialog', { name: '文件版本 · 发布说明.pdf' })
  await expect(versionDialog.getByText('版本 1')).toBeVisible()
  await page.evaluate("window.confirm = () => true")
  await versionDialog.getByRole('button', { name: '回滚' }).click()
  await versionDialog.getByRole('button', { name: '关闭' }).click()

  const fileRow = page.getByRole('row', { name: /选择 发布说明\.pdf/ })
  await fileRow.getByLabel('创建分享').click()
  const shareDialog = page.getByRole('dialog', { name: '创建分享 · 发布说明.pdf' })
  const recipientSearch = shareDialog.getByRole('combobox', { name: '接收人' })
  await recipientSearch.fill('协作')
  await expect(shareDialog.getByRole('option', { name: /协作用户/ })).toBeVisible()
  await recipientSearch.press('Enter')
  await shareDialog.getByRole('button', { name: '创建分享' }).click()
  await expect(shareDialog.getByText('分享已创建')).toBeVisible()
  await shareDialog.getByRole('button', { name: '完成' }).click()

  await page.getByLabel('选择 设计素材').check()
  await page.getByLabel('选择 发布说明.pdf').check()
  await page.getByRole('button', { name: '移到回收站' }).click()
  await expect(page.getByText(/FILE_LOCKED/)).toBeVisible()

  const chooser = page.waitForEvent('filechooser')
  await page.getByRole('button', { name: '上传文件' }).click()
  const fileChooser = await chooser
  await fileChooser.setFiles({
    buffer: Buffer.from('hello'),
    mimeType: 'text/plain',
    name: 'hello.txt',
  })
  await expect(page.getByText('已完成')).toBeVisible({ timeout: 15_000 })
})

test('键盘导航与 125% 缩放保持主要操作可见', async ({ page, browserName }) => {
  test.skip(browserName !== 'chromium', '缩放布局只在 Chromium 执行一次')
  await installMockApi(page)
  await page.goto('/')
  await page.evaluate("document.documentElement.style.zoom = '1.25'")
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: '文件' })).toBeVisible()
  await expect(page.getByRole('button', { name: '上传文件' })).toBeVisible()
})
