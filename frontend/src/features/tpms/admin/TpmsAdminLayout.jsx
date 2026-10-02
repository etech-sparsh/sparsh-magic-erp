import React, { useState, useEffect } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
// eslint-disable-next-line no-unused-vars
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard, Gauge, GitBranch, Building2, AlertTriangle, ScrollText,
  UserCog, ListChecks, BarChart3, UserCircle,
  ChevronLeft, ChevronRight, Menu, X, LogOut, ArrowLeft,
  Sun, Moon, Bell, LayoutGrid,
} from 'lucide-react';
import { useAuth } from '../../../context/AuthContext';
import { useTheme } from '../../../context/ThemeContext';

/**
 * TPMS ▸ Admin Panel navigation config.
 * Paths are nested under /tpms/admin/* and rendered into the <Outlet/> below.
 * `end` marks the index route so it isn't highlighted on child paths.
 */
const ADMIN_NAV = [
  { group: 'Overview', items: [
    { name: 'Admin View',           path: '/tpms/admin',                 icon: LayoutDashboard, end: true },
    { name: 'OM (SMOps) View',      path: '/tpms/admin/om',              icon: Gauge },
  ] },
  { group: 'Clients', items: [
    { name: 'Client View',          path: '/tpms/admin/clients',         icon: Building2 },
    { name: 'Implementation Tracker', path: '/tpms/admin/implementation', icon: GitBranch },
    { name: 'Escalations',          path: '/tpms/admin/escalations',     icon: AlertTriangle },
  ] },
  { group: 'Team', items: [
    { name: 'HOD View',             path: '/tpms/admin/hod',             icon: UserCog },
    { name: 'Employee Tasks',       path: '/tpms/admin/employee-tasks',  icon: ListChecks },
  ] },
  { group: 'Reports', items: [
    { name: 'Logs Report',          path: '/tpms/admin/logs',            icon: ScrollText },
    { name: 'Review Report',        path: '/tpms/admin/reviews',         icon: BarChart3 },
  ] },
];
const ADMIN_LINKS = ADMIN_NAV.flatMap((g) => g.items);

const TpmsAdminLayout = () => {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();

  const [isCollapsed, setIsCollapsed] = useState(false);   // desktop rail toggle
  const [isMobileOpen, setIsMobileOpen] = useState(false); // mobile drawer
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  // Close the mobile drawer whenever the route changes.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { setIsMobileOpen(false); }, [location.pathname]);

  // Derive the current module title for the header.
  const active = [...ADMIN_LINKS]
    .sort((a, b) => b.path.length - a.path.length)
    .find((l) => (l.end ? location.pathname === l.path : location.pathname.startsWith(l.path)));
  const pageTitle = active?.name || 'Admin View';

  const sidebarWidth = isMobile ? 260 : (isCollapsed ? 76 : 260);

  return (
    <div className="flex min-h-screen bg-[var(--bg-main)] text-[var(--text-main)] overflow-x-hidden selection:bg-indigo-100 selection:text-indigo-600">
      {/* ─────────────────────────  SIDEBAR  ───────────────────────── */}
      <motion.aside
        initial={false}
        animate={{ width: sidebarWidth }}
        transition={{ type: 'spring', stiffness: 400, damping: 40 }}
        className={`h-screen fixed left-0 top-0 z-50 flex flex-col overflow-hidden
          bg-[var(--sidebar-bg)] border-r border-[var(--sidebar-border)]
          transform transition-transform duration-300 md:translate-x-0
          ${isMobileOpen ? 'translate-x-0' : '-translate-x-full'}`}
      >
        {/* Brand */}
        <div className={`h-16 flex items-center shrink-0 border-b border-[var(--sidebar-border)]
          ${isCollapsed && !isMobile ? 'justify-center px-2' : 'justify-between px-4'}`}>
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center text-white shrink-0 shadow-sm"
                 style={{ background: 'var(--avatar-bg)' }}>
              <LayoutGrid size={18} />
            </div>
            {(!isCollapsed || isMobile) && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex flex-col min-w-0">
                <span className="text-[14px] font-extrabold tracking-tight leading-none">TPMS</span>
                <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--accent-indigo)] mt-1">
                  Admin Panel
                </span>
              </motion.div>
            )}
          </div>
          {isMobile && (
            <button onClick={() => setIsMobileOpen(false)}
                    className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]">
              <X size={18} />
            </button>
          )}
        </div>

        {/* Nav links (grouped) */}
        <nav className="flex-1 px-3 py-4 overflow-y-auto no-scrollbar">
          {ADMIN_NAV.map((section, si) => (
            <div key={section.group} className={si > 0 ? 'mt-4' : ''}>
              {(!isCollapsed || isMobile) ? (
                <p className="px-2.5 mb-1.5 text-[9.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]/80">{section.group}</p>
              ) : (si > 0 && <div className="mx-2 my-2 border-t border-[var(--sidebar-border)]" />)}
              <div className="space-y-1">
                {section.items.map((link) => (
                  <NavLink
                    key={link.path}
                    to={link.path}
                    end={link.end}
                    className={({ isActive }) => `
                      group flex items-center gap-3 p-2.5 rounded-lg transition-colors relative
                      ${isActive
                        ? 'text-white font-bold shadow-sm'
                        : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]'}
                      ${isCollapsed && !isMobile ? 'justify-center' : ''}`}
                    style={({ isActive }) => (isActive ? { background: 'var(--btn-primary)' } : undefined)}
                  >
                    <link.icon size={18} className="shrink-0 transition-transform group-hover:scale-105" />
                    {(!isCollapsed || isMobile) && (
                      <span className="text-[13px] tracking-tight font-medium">{link.name}</span>
                    )}
                    {isCollapsed && !isMobile && (
                      <div className="absolute left-full ml-4 px-2.5 py-1.5 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-main)] text-[10px] font-bold uppercase tracking-widest rounded-lg opacity-0 group-hover:opacity-100 pointer-events-none transition-all duration-300 z-50 shadow-lg whitespace-nowrap">
                        {link.name}
                      </div>
                    )}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        {/* Footer: back to Sparsh + logout */}
        <div className="p-3 border-t border-[var(--sidebar-border)] space-y-1">
          <button
            onClick={() => navigate('/')}
            className={`w-full flex items-center gap-3 p-2.5 rounded-lg text-[var(--text-muted)]
              hover:bg-[var(--input-bg)] hover:text-[var(--text-main)] transition-all
              ${isCollapsed && !isMobile ? 'justify-center' : ''}`}
          >
            <ArrowLeft size={18} />
            {(!isCollapsed || isMobile) && <span className="text-[13px] font-bold tracking-tight">Back to Sparsh</span>}
          </button>
          <button
            onClick={logout}
            className={`w-full flex items-center gap-3 p-2.5 rounded-lg text-[var(--text-muted)]
              hover:bg-[var(--accent-red-bg)] hover:text-[var(--accent-red)] transition-all
              ${isCollapsed && !isMobile ? 'justify-center' : ''}`}
          >
            <LogOut size={18} />
            {(!isCollapsed || isMobile) && <span className="text-[13px] font-bold tracking-tight">Logout</span>}
          </button>
        </div>
      </motion.aside>

      {/* Backdrop for mobile drawer */}
      {isMobileOpen && (
        <div
          className="fixed inset-0 bg-black/40 backdrop-blur-xs z-40 md:hidden animate-in fade-in duration-200"
          onClick={() => setIsMobileOpen(false)}
        />
      )}

      {/* Desktop spacer so content clears the fixed sidebar */}
      <div className="shrink-0 hidden md:block transition-all duration-300"
           style={{ width: isCollapsed ? 76 : 260 }} />

      {/* ─────────────────────────  MAIN  ───────────────────────── */}
      <div className="flex-1 flex flex-col relative w-full h-screen overflow-y-auto no-scrollbar scroll-smooth">
        {/* Header bar */}
        <header className="h-16 px-4 sm:px-6 flex items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--bg-card)] sticky top-0 z-30">
          <div className="flex items-center gap-2 min-w-0">
            {/* Mobile menu */}
            <button
              onClick={() => setIsMobileOpen(true)}
              className="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-main)] hover:bg-[var(--input-bg)] md:hidden"
              aria-label="Open menu"
            >
              <Menu size={20} />
            </button>
            {/* Desktop collapse toggle */}
            <button
              onClick={() => setIsCollapsed((c) => !c)}
              className="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-main)] hover:bg-[var(--input-bg)] hidden md:inline-flex"
              aria-label="Toggle sidebar"
            >
              {isCollapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
            </button>
            <div className="min-w-0">
              <h1 className="text-[16px] font-extrabold tracking-tight truncate">{pageTitle}</h1>
            </div>
          </div>

          <div className="flex items-center gap-2 sm:gap-3 shrink-0">
            {/* Theme toggle (reuses Navbar pattern) */}
            <div className="flex items-center gap-1 bg-[var(--input-bg)] p-1 rounded-lg border border-[var(--input-border)]">
              <button onClick={toggleTheme}
                className={`p-1.5 rounded-md transition-all ${theme === 'light' ? 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)] shadow-sm' : 'text-[var(--text-muted)]'}`}>
                <Sun size={14} />
              </button>
              <button onClick={toggleTheme}
                className={`p-1.5 rounded-md transition-all ${theme === 'dark' ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shadow-sm' : 'text-[var(--text-muted)]'}`}>
                <Moon size={14} />
              </button>
            </div>

            <button className="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-orange)] hover:bg-[var(--accent-orange-bg)] transition-all relative">
              <Bell size={18} />
            </button>

            <div className="h-6 w-px bg-[var(--border)] hidden sm:block" />

            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg flex items-center justify-center text-white font-bold text-[11px]"
                   style={{ background: 'var(--avatar-bg)' }}>
                {user?.full_name?.charAt(0) || 'A'}
              </div>
              <div className="hidden sm:flex flex-col items-start">
                <span className="text-[13px] font-bold leading-none">{user?.full_name || 'Admin'}</span>
                <span className="text-[10px] text-[var(--accent-indigo)] font-bold uppercase tracking-tight mt-0.5">
                  {user?.role || 'admin'}
                </span>
              </div>
            </div>
          </div>
        </header>

        {/* Sub-module render area */}
        <main className="flex-1 px-4 sm:px-6 py-6 w-full">
          <div className="max-w-[1600px] mx-auto">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
};

export default TpmsAdminLayout;
