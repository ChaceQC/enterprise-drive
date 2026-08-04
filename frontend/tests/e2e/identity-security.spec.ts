import { expect, test } from '@playwright/test'

import { installMockApi } from './mock-api'

test.describe.configure({ mode: 'serial' })
test.setTimeout(90_000)

test('首次登录强制改密后重新登录', async ({ page }) => {
  await installMockApi(page, {
    authenticated: true,
    mustChangePassword: true,
  })
  await page.goto('/', { waitUntil: 'domcontentloaded' })

  await expect(page.getByRole('heading', { name: '首次登录必须修改密码' })).toBeVisible()
  await page.getByLabel('当前密码').fill('Initial-Password1!')
  await page.getByLabel('新密码', { exact: true }).fill('Next-Password1!')
  await page.getByLabel('确认新密码', { exact: true }).fill('Next-Password1!')
  await page.getByRole('button', { name: '修改密码并重新登录' }).click()

  await expect(page.getByRole('heading', { name: '登录' })).toBeVisible()
  await page.getByLabel('用户名').fill('admin')
  await page.getByLabel('密码').fill('Next-Password1!')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('heading', { name: '我的文件' })).toBeVisible()
})

test('验证码、锁定反馈与 OIDC 登录入口', async ({ page }) => {
  await installMockApi(page, {
    authenticated: false,
    loginChallenge: true,
  })
  await page.goto('/', { waitUntil: 'domcontentloaded' })

  await page.getByLabel('用户名').fill('admin')
  await page.getByLabel('密码').fill('Wrong-Password1!')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByLabel('验证码')).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('验证码')

  await page.getByLabel('验证码').fill('captcha-e2e-token')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('账号已临时锁定')
  await expect(page.getByText(/预计解锁时间/)).toBeVisible()

  await expect(page.getByRole('button', { name: '使用 企业 SSO 登录' })).toBeVisible()
})

test('浏览器会话吊销与 OIDC 绑定入口', async ({ page }) => {
  await installMockApi(page)
  await page.goto('/account', { waitUntil: 'domcontentloaded' })

  await expect(page.getByText('Playwright managed browser')).toBeVisible()
  await page.getByRole('button', { name: '吊销会话' }).click()
  await expect(page.getByText('当前没有可管理的浏览器会话。')).toBeVisible()

  await expect(page.getByRole('heading', { name: '企业单点登录绑定' })).toBeVisible()
  await expect(page.getByRole('button', { name: '绑定 企业 SSO' })).toBeVisible()
})

test('管理账号与身份源治理不回显密钥', async ({ page }) => {
  test.slow()
  await installMockApi(page)
  await page.goto('/admin/security', { waitUntil: 'domcontentloaded' })

  const securityRow = page.getByRole('row').filter({ hasText: '系统管理员' })
  await expect(securityRow).toContainText('锁定至')
  await securityRow.getByRole('button', { name: '解锁' }).click()
  await expect(securityRow).toContainText('正常')

  await page.getByRole('button', { name: '重置密码' }).click()
  const resetDialog = page.getByRole('dialog', { name: /重置密码/ })
  await resetDialog.getByLabel('临时密码', { exact: true }).fill('Temporary-Password1!')
  await resetDialog.getByLabel('确认临时密码', { exact: true }).fill('Temporary-Password1!')
  await resetDialog.getByRole('button', { name: '重置并吊销全部会话' }).click()
  await expect(page.getByRole('dialog', { name: /重置密码/ })).toHaveCount(0)
  await expect(securityRow).toContainText('是')

  await page.goto('/admin/identity', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'OIDC Provider' })).toBeVisible()
  const oidcRow = page.getByRole('row').filter({ hasText: '企业 SSO' })
  await expect(oidcRow).toContainText('已配置')
  await expect(page.getByText('OIDC_CLIENT_SECRET')).toHaveCount(0)
  await oidcRow.getByRole('button', { name: '测试连接' }).click()
  await expect(oidcRow).toContainText('发现文档连接成功')

  await page.getByRole('button', { name: '新建 OIDC Provider' }).click()
  const oidcDialog = page.getByRole('dialog', { name: '新建 OIDC Provider' })
  await oidcDialog.getByLabel('显示名称').fill('新 SSO')
  await oidcDialog.getByLabel('唯一标识').fill('new-sso')
  await oidcDialog.getByLabel('Issuer URL').fill('https://new-idp.example.com')
  await oidcDialog.getByLabel('Client ID').fill('new-client')
  await oidcDialog.getByLabel('客户端密钥引用').fill('env:OIDC_CLIENT_SECRET')
  await oidcDialog.getByRole('button', { name: '创建 OIDC Provider' }).click()
  await expect(page.getByRole('row').filter({ hasText: '新 SSO' })).toContainText('已配置')
  await expect(page.getByText('env:OIDC_CLIENT_SECRET')).toHaveCount(0)

  const ldapRow = page.getByRole('row').filter({ hasText: 'corp-directory' })
  await ldapRow.getByRole('button', { name: '测试连接' }).click()
  await expect(ldapRow).toContainText('连接成功')
  await ldapRow.getByRole('button', { name: 'Dry-run' }).click()
  await expect(page.getByRole('cell', { name: 'Dry-run', exact: true })).toBeVisible()

  const runRow = page.getByRole('row').filter({ hasText: /企业目录.*增量/ })
  await runRow.getByRole('button', { name: '查看冲突' }).click()
  await expect(page.getByRole('heading', { name: '同步冲突' })).toBeVisible()
  await expect(page.getByText('existing-user')).toBeVisible()

  await page.getByRole('button', { name: '新建 LDAP 身份源' }).click()
  const ldapDialog = page.getByRole('dialog', { name: '新建 LDAP 身份源' })
  await ldapDialog.getByLabel('显示名称').fill('新目录')
  await ldapDialog.getByLabel('唯一标识').fill('new-directory')
  await ldapDialog.getByLabel('LDAP Server URL').fill('ldaps://new-ldap.example.com')
  await ldapDialog.getByLabel('Base DN', { exact: true }).fill('dc=new,dc=example,dc=com')
  await ldapDialog.getByLabel('用户 Base DN', { exact: true }).fill('ou=users,dc=new,dc=example,dc=com')
  await ldapDialog.getByLabel('Bind 密码引用').fill('env:LDAP_BIND_PASSWORD')
  await ldapDialog.getByRole('button', { name: '创建 LDAP 身份源' }).click()
  await expect(page.getByRole('row').filter({ hasText: '新目录' })).toContainText('已配置')
  await expect(page.getByText('env:LDAP_BIND_PASSWORD')).toHaveCount(0)
})
