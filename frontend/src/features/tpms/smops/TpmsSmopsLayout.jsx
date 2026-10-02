import React, { useState, useEffect } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
// eslint-disable-next-line no-unused-vars
import { motion } from 'framer-motion';
import {
  LayoutDashboard, Activity, ClipboardList, BarChart3, UserCircle,
  ChevronLeft, ChevronRight, Menu, X, LogOut, ArrowLeft,
  Sun, Moon, Bell, Building2, ChevronDown, Check, Search,
} from 'lucide-react';
import { useAuth } from '../../../context/AuthContext';
import { useTheme } from '../../../context/ThemeContext';
import { CompanyProvider } from './CompanyContext';

const SMOPS_NAV = [
  { group: 'Overview', items: [
    { name: 'Dashboard',      path: '/tpms/smops',              icon: LayoutDashboard, end: true },
  ] },
  { group: 'Monitoring', items: [
    { name: 'HOD Activity',   path: '/tpms/smops/hod-activity', icon: Activity },
    { name: 'Employee Task',  path: '/tpms/smops/tasks',        icon: ClipboardList },
  ] },
  { group: 'Reports', items: [
    { name: 'Review Report',  path: '/tpms/smops/reviews',      icon: BarChart3 },
  ] },
];
const SMOPS_LINKS = SMOPS_NAV.flatMap((g) => g.items);

const SmopsShell = () => {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();

  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { setIsMobileOpen(false); }, [location.pathname]);

  const active = [...SMOPS_LINKS]
    .sort((a, b) => b.path.length - a.path.length)
    .find((l) => (l.end ? location.pathname === l.path : location.pathname.startsWith(l.path)));
  const pageTitle = active?.name || 'Dashboard';

  const sidebarWidth = isMobile ? 260 : (isCollapsed ? 76 : 260);

  return (
    <div className="flex min-h-screen bg-[var(--bg-main)] text-[var(--text-main)] overflow-x-hidden selection:bg-indigo-100 selection:text-indigo-600">
      {/* Sidebar */}
      <motion.aside
        initial={false}
        animate={{ width: sidebarWidth }}
        transition={{ type: 'spring', stiffness: 400, damping: 40 }}
        className={`h-screen fixed left-0 top-0 z-50 flex flex-col overflow-hidden
          bg-[var(--sidebar-bg)] border-r border-[var(--sidebar-border)]
          transform transition-transform duration-300 md:translate-x-0
          ${isMobileOpen ? 'translate-x-0' : '-translate-x-full'}`}
      >
        <div className={`h-16 flex items-center shrink-0 border-b border-[var(--sidebar-border)]
          ${isCollapsed && !isMobile ? 'justify-center px-2' : 'justify-between px-4'}`}>
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center text-white shrink-0 shadow-sm" style={{ background: 'var(--avatar-bg)' }}>
              <Building2 size={18} />
            </div>
            {(!isCollapsed || isMobile) && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex flex-col min-w-0">
                <span className="text-[14px] font-extrabold tracking-tight leading-none">TPMS</span>
                <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--accent-indigo)] mt-1">SMOPS Panel</span>
              </motion.div>
            )}
          </div>
          {isMobile && (
            <button onClick={() => setIsMobileOpen(false)} className="p-1.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)]"><X size={18} /></button>
          )}
        </div>

        <nav className="flex-1 px-3 py-4 overflow-y-auto no-scrollbar">
          {SMOPS_NAV.map((section, si) => (
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

        <div className="p-3 border-t border-[var(--sidebar-border)] space-y-1">
          <button onClick={() => navigate('/')}
            className={`w-full flex items-center gap-3 p-2.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)] transition-all ${isCollapsed && !isMobile ? 'justify-center' : ''}`}>
            <ArrowLeft size={18} />
            {(!isCollapsed || isMobile) && <span className="text-[13px] font-bold tracking-tight">Back to Sparsh</span>}
          </button>
          <button onClick={logout}
            className={`w-full flex items-center gap-3 p-2.5 rounded-lg text-[var(--text-muted)] hover:bg-[var(--accent-red-bg)] hover:text-[var(--accent-red)] transition-all ${isCollapsed && !isMobile ? 'justify-center' : ''}`}>
            <LogOut size={18} />
            {(!isCollapsed || isMobile) && <span className="text-[13px] font-bold tracking-tight">Logout</span>}
          </button>
        </div>
      </motion.aside>

      {isMobileOpen && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-xs z-40 md:hidden animate-in fade-in duration-200" onClick={() => setIsMobileOpen(false)} />
      )}

      <div className="shrink-0 hidden md:block transition-all duration-300" style={{ width: isCollapsed ? 76 : 260 }} />

      {/* Main */}
      <div className="flex-1 flex flex-col relative w-full h-screen overflow-y-auto no-scrollbar scroll-smooth">
        <header className="h-16 px-4 sm:px-6 flex items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--bg-card)] sticky top-0 z-30">
          <div className="flex items-center gap-2 min-w-0">
            <button onClick={() => setIsMobileOpen(true)} className="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-main)] hover:bg-[var(--input-bg)] md:hidden" aria-label="Open menu">
              <Menu size={20} />
            </button>
            <button onClick={() => setIsCollapsed((c) => !c)} className="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-main)] hover:bg-[var(--input-bg)] hidden md:inline-flex" aria-label="Toggle sidebar">
              {isCollapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
            </button>
            <div className="min-w-0">
              <h1 className="text-[16px] font-extrabold tracking-tight truncate">{pageTitle}</h1>
            </div>
          </div>

          <div className="flex items-center gap-2 sm:gap-3 shrink-0">
            <div className="hidden sm:flex items-center gap-1 bg-[var(--input-bg)] p-1 rounded-lg border border-[var(--input-border)]">
              <button onClick={toggleTheme} className={`p-1.5 rounded-md transition-all ${theme === 'light' ? 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)] shadow-sm' : 'text-[var(--text-muted)]'}`}><Sun size={14} /></button>
              <button onClick={toggleTheme} className={`p-1.5 rounded-md transition-all ${theme === 'dark' ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shadow-sm' : 'text-[var(--text-muted)]'}`}><Moon size={14} /></button>
            </div>

            <button className="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--accent-orange)] hover:bg-[var(--accent-orange-bg)] transition-all hidden sm:inline-flex"><Bell size={18} /></button>

            <div className="h-6 w-px bg-[var(--border)] hidden lg:block" />

            <div className="hidden lg:flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg flex items-center justify-center text-white font-bold text-[11px]" style={{ background: 'var(--avatar-bg)' }}>
                {user?.full_name?.charAt(0) || 'S'}
              </div>
              <div className="flex flex-col items-start">
                <span className="text-[13px] font-bold leading-none">{user?.full_name || 'SMOPS'}</span>
                <span className="text-[10px] text-[var(--accent-indigo)] font-bold uppercase tracking-tight mt-0.5">{user?.role || 'smops'}</span>
              </div>
            </div>
          </div>
        </header>

        <main className="flex-1 px-4 sm:px-6 py-6 w-full">
          <div className="max-w-[1600px] mx-auto">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
};

const TpmsSmopsLayout = () => (
  <CompanyProvider>
    <SmopsShell />
  </CompanyProvider>
);

export default TpmsSmopsLayout;
