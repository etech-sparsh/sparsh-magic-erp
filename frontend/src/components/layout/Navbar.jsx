import React, { useState, useEffect } from 'react';
import { useTheme } from '../../context/ThemeContext';
import { useAuth } from '../../context/AuthContext';
import { Link } from 'react-router-dom';
import {
  Sun, Moon, Bell, Search, ChevronDown, Settings, User, LogOut, Menu
} from 'lucide-react';
import NotificationDrawer from './NotificationDrawer';
import api from '../../services/api';

const Navbar = ({ onMenuClick }) => {
  const { theme, toggleTheme } = useTheme();
  const { user, logout } = useAuth();

  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);

  useEffect(() => {
    const fetchUnreadCount = async () => {
      try {
        const response = await api.get('/notifications/unread-count');
        setUnreadCount(response.data.count);
      } catch (error) {
        console.error('Error fetching unread count:', error);
      }
    };

    if (user) {
      fetchUnreadCount();
      // Optionally poll every 30 seconds
      const interval = setInterval(fetchUnreadCount, 30000);
      return () => clearInterval(interval);
    }
  }, [user]);

  return (
    <nav className="h-14 px-4 sm:px-6 flex items-center justify-between gap-3 border-b border-[var(--border)] bg-[var(--bg-card)] sticky top-0 z-30 transition-all duration-300">
      <div className="flex items-center gap-3 flex-1 max-w-sm min-w-0">
        <button
          onClick={onMenuClick}
          className="p-2 text-[var(--text-muted)] hover:text-[var(--text-main)] hover:bg-[var(--input-bg)] rounded-lg md:hidden transition-all cursor-pointer shrink-0"
          aria-label="Open Menu"
        >
          <Menu size={20} />
        </button>
        <div className="relative flex-1 hidden sm:block">
          <Search size={14} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            type="text"
            placeholder="Search..."
            className="w-full pl-10 pr-4 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-lg focus:border-[var(--accent-indigo)] outline-none text-[13px] font-medium text-[var(--text-main)] transition-all placeholder:text-[var(--text-muted)]"
          />
        </div>
      </div>

      <div className="flex items-center gap-2 sm:gap-3 md:gap-4 shrink-0">
        <div className="flex items-center gap-1 bg-[var(--input-bg)] p-1 rounded-lg border border-[var(--input-border)]">
          <button
            onClick={toggleTheme}
            className={`p-1.5 rounded-md transition-all ${theme === 'light' ? 'bg-[var(--accent-orange-bg)] text-[var(--accent-orange)] shadow-sm' : 'text-[var(--text-muted)]'}`}
          >
            <Sun size={14} />
          </button>
          <button
            onClick={toggleTheme}
            className={`p-1.5 rounded-md transition-all ${theme === 'dark' ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shadow-sm' : 'text-[var(--text-muted)]'}`}
          >
            <Moon size={14} />
          </button>
        </div>

        <button
          onClick={() => setIsNotificationsOpen(true)}
          className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-orange)] hover:bg-[var(--accent-orange-bg)] rounded-lg transition-all relative"
        >
          <Bell size={18} />
          {unreadCount > 0 && (
            <span className="absolute top-1 right-1 min-w-[16px] h-4 px-1 flex items-center justify-center bg-[var(--accent-red)] text-white text-[9px] font-bold border border-[var(--bg-card)] rounded-full">
              {unreadCount > 9 ? '9+' : unreadCount}
            </span>
          )}
        </button>

        {user?.role === 'superadmin' && (
          <Link to="/admin/settings" className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] rounded-lg transition-all">
            <Settings size={18} />
          </Link>
        )}

        <div className="h-6 w-px bg-[var(--border)] mx-1 hidden sm:block"></div>

        <div className="relative">
          <button
            onClick={() => setIsProfileOpen(!isProfileOpen)}
            className="flex items-center gap-2 p-1 pl-1 pr-2 hover:bg-[var(--input-bg)] rounded-lg transition-all group"
          >
            <div className="w-8 h-8 rounded-lg flex items-center justify-center text-white font-bold text-[10px]" style={{ background: 'var(--avatar-bg)' }}>
              {user?.full_name?.charAt(0) || 'U'}
            </div>
            <div className="flex flex-col items-start sr-only sm:not-sr-only">
              <span className="text-[13px] font-bold text-[var(--text-main)] leading-none">{user?.full_name || 'Guest'}</span>
              <span className="text-[10px] text-[var(--accent-indigo)] font-bold uppercase tracking-tight mt-0.5">{user?.role || 'User'}</span>
            </div>
            <ChevronDown size={12} className={`text-[var(--text-muted)] ml-1 transition-transform duration-300 ${isProfileOpen ? 'rotate-180' : ''}`} />
          </button>

          {isProfileOpen && (
            <div className="absolute right-0 top-12 w-48 bg-[var(--bg-card)] border border-[var(--border)] rounded-xl shadow-xl z-50 overflow-hidden py-1 animate-in fade-in slide-in-from-top-2">
              <Link
                to="/profile"
                onClick={() => setIsProfileOpen(false)}
                className="flex items-center gap-3 px-4 py-2 text-[13px] font-medium text-[var(--text-main)] hover:bg-[var(--input-bg)] transition-all"
              >
                <div className="w-7 h-7 rounded-lg bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center">
                  <User size={14} />
                </div>
                Manage Profile
              </Link>
              <button
                onClick={() => { logout(); setIsProfileOpen(false); }}
                className="w-full flex items-center gap-3 px-4 py-2 text-[13px] font-medium text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] transition-all"
              >
                <div className="w-7 h-7 rounded-lg bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center">
                  <LogOut size={14} />
                </div>
                Sign Out
              </button>
            </div>
          )}
        </div>
      </div>

      <NotificationDrawer
        isOpen={isNotificationsOpen}
        onClose={() => setIsNotificationsOpen(false)}
        onCountChange={setUnreadCount}
      />
    </nav>
  );
};

export default Navbar;
