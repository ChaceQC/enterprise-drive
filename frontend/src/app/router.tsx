import {
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'

import { ProtectedShell, AdminGuard } from './AppShell'
import { AccountPage } from '../modules/account/AccountPage'
import { AdminPage } from '../modules/admin/AdminPage'
import { DrivePage } from '../modules/files/DrivePage'
import { NotificationsPage } from '../modules/shares/NotificationsPage'
import { OidcCallbackPage } from '../modules/auth/OidcCallbackPage'
import { PublicSharePage } from '../modules/shares/PublicSharePage'
import { SharesPage } from '../modules/shares/SharesPage'
import { SearchPage } from '../modules/search/SearchPage'
import { TrashPage } from '../modules/trash/TrashPage'

const rootRoute = createRootRoute()

const protectedRoute = createRoute({
  component: ProtectedShell,
  getParentRoute: () => rootRoute,
  id: 'protected',
})

const driveRoute = createRoute({
  component: DrivePage,
  getParentRoute: () => protectedRoute,
  path: '/',
})

const searchRoute = createRoute({
  component: SearchPage,
  getParentRoute: () => protectedRoute,
  path: '/search',
})

const trashRoute = createRoute({
  component: TrashPage,
  getParentRoute: () => protectedRoute,
  path: '/trash',
})

const sharesRoute = createRoute({
  component: SharesPage,
  getParentRoute: () => protectedRoute,
  path: '/shares',
})

const notificationsRoute = createRoute({
  component: NotificationsPage,
  getParentRoute: () => protectedRoute,
  path: '/notifications',
})

const accountRoute = createRoute({
  component: AccountPage,
  getParentRoute: () => protectedRoute,
  path: '/account',
})

const adminRoute = createRoute({
  component: AdminGuard,
  getParentRoute: () => protectedRoute,
  path: '/admin',
})

const adminIndexRoute = createRoute({
  component: AdminPage,
  getParentRoute: () => adminRoute,
  path: '/',
})

const adminUsersRoute = createRoute({
  component: AdminPage,
  getParentRoute: () => adminRoute,
  path: '/users',
})

const adminOrganizationRoute = createRoute({
  component: AdminPage,
  getParentRoute: () => adminRoute,
  path: '/organization',
})

const adminSpacesRoute = createRoute({
  component: AdminPage,
  getParentRoute: () => adminRoute,
  path: '/spaces',
})

const adminQuotasRoute = createRoute({
  component: AdminPage,
  getParentRoute: () => adminRoute,
  path: '/quotas',
})

const adminSecurityRoute = createRoute({
  component: AdminPage,
  getParentRoute: () => adminRoute,
  path: '/security',
})

const adminIdentityRoute = createRoute({
  component: AdminPage,
  getParentRoute: () => adminRoute,
  path: '/identity',
})

const adminAuditRoute = createRoute({
  component: AdminPage,
  getParentRoute: () => adminRoute,
  path: '/audit',
})

const adminMaintenanceRoute = createRoute({
  component: AdminPage,
  getParentRoute: () => adminRoute,
  path: '/maintenance',
})

const adminExportsRoute = createRoute({
  component: AdminPage,
  getParentRoute: () => adminRoute,
  path: '/exports',
})

const adminGovernanceRoute = createRoute({
  component: AdminPage,
  getParentRoute: () => adminRoute,
  path: '/governance',
})

const publicShareRoute = createRoute({
  component: PublicSharePage,
  getParentRoute: () => rootRoute,
  path: '/public-share',
})

const oidcCallbackRoute = createRoute({
  component: OidcCallbackPage,
  getParentRoute: () => rootRoute,
  path: '/auth/oidc/callback',
})

const routeTree = rootRoute.addChildren([
  protectedRoute.addChildren([
    driveRoute,
    searchRoute,
    trashRoute,
    sharesRoute,
    notificationsRoute,
    accountRoute,
    adminRoute.addChildren([
      adminIndexRoute,
      adminUsersRoute,
      adminOrganizationRoute,
      adminSpacesRoute,
      adminQuotasRoute,
      adminSecurityRoute,
      adminIdentityRoute,
      adminAuditRoute,
      adminMaintenanceRoute,
      adminExportsRoute,
      adminGovernanceRoute,
    ]),
  ]),
  publicShareRoute,
  oidcCallbackRoute,
])

export const router = createRouter({
  defaultPreload: 'intent',
  routeTree,
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
