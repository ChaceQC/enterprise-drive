import {
  Activity,
  Bell,
  Files,
  HardDrive,
  LogOut,
  Search,
  Settings2,
  Share2,
  ShieldCheck,
  Trash2,
  UserRound,
} from 'lucide-react'
import {
  Link,
  Outlet,
  useRouterState,
} from '@tanstack/react-router'

import { useAuth } from './useAuth'
import { LoginForm } from '../modules/auth/LoginForm'

const userNavigation = [
  { icon: Files, label: '文件', to: '/' },
  { icon: Search, label: '搜索', to: '/search' },
  { icon: Trash2, label: '回收站', to: '/trash' },
  { icon: Share2, label: '分享', to: '/shares' },
  { icon: Bell, label: '通知', to: '/notifications' },
]

function isActivePath(pathname: string, to: string) {
  return to === '/' ? pathname === '/' : pathname.startsWith(to)
}

export function ProtectedShell() {
  const { error, isPending, logout, status, user } = useAuth()
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })

  if (status === 'loading') {
    return (
      <main className="auth-loading">
        <div className="brand-mark"><HardDrive size={26} /></div>
        <p>正在恢复安全会话…</p>
      </main>
    )
  }

  if (status === 'anonymous') {
    return (
      <main className="login-canvas">
        <LoginForm />
      </main>
    )
  }

  return (
    <div className="workspace-shell">
      <aside className="navigation-rail">
        <div className="brand-lockup">
          <span className="brand-mark"><HardDrive size={20} /></span>
          <div>
            <strong>企业网盘</strong>
            <span>Web 0.7</span>
          </div>
        </div>

        <nav aria-label="主导航">
          <p className="nav-label">工作区</p>
          {userNavigation.map(({ icon: Icon, label, to }) => (
            <Link
              aria-current={isActivePath(pathname, to) ? 'page' : undefined}
              className={isActivePath(pathname, to) ? 'active' : ''}
              key={to}
              to={to}
            >
              <Icon aria-hidden="true" size={18} strokeWidth={1.8} />
              <span>{label}</span>
            </Link>
          ))}
          <p className="nav-label">账户</p>
          <Link
            className={isActivePath(pathname, '/account') ? 'active' : ''}
            to="/account"
          >
            <UserRound size={18} strokeWidth={1.8} />
            <span>账户与设备</span>
          </Link>
          {user?.is_super_admin ? (
            <Link
              className={isActivePath(pathname, '/admin') ? 'active' : ''}
              to="/admin"
            >
              <ShieldCheck size={18} strokeWidth={1.8} />
              <span>管理后台</span>
            </Link>
          ) : null}
        </nav>

        <div className="rail-footer">
          <div className="identity">
            <span>{user?.display_name.slice(0, 1)}</span>
            <div>
              <strong>{user?.display_name}</strong>
              <small>{user?.username}</small>
            </div>
          </div>
          <button
            aria-label="退出登录"
            className="icon-button neutral"
            disabled={isPending}
            onClick={() => void logout().catch(() => undefined)}
            type="button"
          >
            <LogOut size={17} />
          </button>
        </div>
      </aside>

      <main className="workspace-main">
        {error ? (
          <div className="session-warning">
            <Activity size={16} />
            <span>{error.message}</span>
          </div>
        ) : null}
        <Outlet />
      </main>
    </div>
  )
}

export function AdminGuard() {
  const { user } = useAuth()
  if (!user?.is_super_admin) {
    return (
      <section className="content-plane narrow">
        <div className="empty-state">
          <Settings2 size={30} />
          <strong>需要系统管理员权限</strong>
          <p>页面守卫只用于体验，后端仍会再次校验管理权限。</p>
          <Link className="button-link" to="/">返回文件区</Link>
        </div>
      </section>
    )
  }
  return <Outlet />
}
