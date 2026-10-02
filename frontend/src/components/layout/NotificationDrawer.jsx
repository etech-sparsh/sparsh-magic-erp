import React, { useState, useEffect } from 'react';
import { X, Bell, BellOff, Info, CheckCircle, AlertTriangle, AlertCircle } from 'lucide-react';
import api from '../../services/api';

const NotificationDrawer = ({ isOpen, onClose, onCountChange }) => {
  const [notifications, setNotifications] = useState([]);
  const [loading, setLoading] = useState(false);

  const fetchNotifications = async () => {
    try {
      setLoading(true);
      const response = await api.get('/notifications/');
      setNotifications(response.data);
      const unreadCount = response.data.filter(n => !n.is_read).length;
      if (onCountChange) onCountChange(unreadCount);
    } catch (error) {
      console.error('Error fetching notifications:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchNotifications();
    }
  }, [isOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  const markAsRead = async (id) => {
    try {
      await api.put(`/notifications/${id}/read`);
      setNotifications(notifications.map(n => 
        n._id === id ? { ...n, is_read: true } : n
      ));
      const unreadCount = notifications.filter(n => n._id !== id ? !n.is_read : false).length;
      if (onCountChange) onCountChange(unreadCount);
    } catch (error) {
      console.error('Error marking notification as read:', error);
    }
  };

  const markAllRead = async () => {
    try {
      await api.put('/notifications/mark-all-read');
      setNotifications(notifications.map(n => ({ ...n, is_read: true })));
      if (onCountChange) onCountChange(0);
    } catch (error) {
      console.error('Error marking all as read:', error);
    }
  };

  const deleteNotification = async (id) => {
    try {
      await api.delete(`/notifications/${id}`);
      const updated = notifications.filter(n => n._id !== id);
      setNotifications(updated);
      const unreadCount = updated.filter(n => !n.is_read).length;
      if (onCountChange) onCountChange(unreadCount);
    } catch (error) {
      console.error('Error deleting notification:', error);
    }
  };

  const formatTime = (dateString) => {
    const now = new Date();
    const then = new Date(dateString);
    const diff = Math.floor((now - then) / 1000);
    
    if (diff < 60) return 'just now';
    const mins = Math.floor(diff / 60);
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    if (days < 30) return `${days}d ago`;
    return then.toLocaleDateString();
  };

  const getIcon = (type) => {
    switch (type) {
      case 'success': return <CheckCircle size={16} className="text-[var(--accent-green)]" />;
      case 'warning': return <AlertTriangle size={16} className="text-[var(--accent-orange)]" />;
      case 'error': return <AlertCircle size={16} className="text-[var(--accent-red)]" />;
      default: return <Info size={16} className="text-[var(--accent-indigo)]" />;
    }
  };

  const getBg = (type) => {
    switch (type) {
      case 'success': return 'bg-[var(--accent-green-bg)]';
      case 'warning': return 'bg-[var(--accent-orange-bg)]';
      case 'error': return 'bg-[var(--accent-red-bg)]';
      default: return 'bg-[var(--accent-indigo-bg)]';
    }
  };

  return (
    <>
      {/* Backdrop */}
      {isOpen && (
        <div 
          className="fixed inset-0 bg-black/20 backdrop-blur-sm z-40 transition-opacity duration-300"
          onClick={onClose}
        />
      )}

      {/* Drawer */}
      <div className={`fixed right-0 top-0 h-screen w-full max-w-sm bg-[var(--bg-card)] border-l border-[var(--border)] shadow-2xl z-50 transform transition-transform duration-300 ease-out ${isOpen ? 'translate-x-0' : 'translate-x-full'}`}>
        <div className="flex flex-col h-full">
          {/* Header */}
          <div className="p-4 border-b border-[var(--border)] flex items-center justify-between bg-[var(--bg-card)]">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center">
                <Bell size={18} />
              </div>
              <h2 className="text-lg font-bold text-[var(--text-main)]">Notifications</h2>
            </div>
            <div className="flex items-center gap-1">
              <button 
                onClick={markAllRead}
                className="p-0 text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] rounded-lg transition-all"
                title="Mark all as read"
              >
                <CheckCircle size={18} />
              </button>
              <button 
                onClick={onClose}
                className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] rounded-lg transition-all"
              >
                <X size={20} />
              </button>
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto p-2 space-y-2 no-scrollbar">
            {loading && notifications.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-64 text-[var(--text-muted)]">
                <div className="w-8 h-8 border-2 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin mb-4"></div>
                <p className="text-sm font-medium">Loading notifications...</p>
              </div>
            ) : notifications.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-64 text-[var(--text-muted)] opacity-50">
                <BellOff size={48} className="mb-4" />
                <p className="text-sm font-medium">No notifications yet</p>
              </div>
            ) : (
              notifications.map((n) => (
                <div 
                  key={n._id}
                  className={`group relative p-4 rounded-xl border transition-all duration-300 ${n.is_read ? 'bg-transparent border-[var(--border)]' : 'bg-[var(--input-bg)] border-[var(--accent-indigo)]/20 shadow-sm'}`}
                >
                  <div className="flex gap-4">
                    <div className={`shrink-0 w-8 h-8 rounded-lg flex items-center justify-center ${getBg(n.type)}`}>
                      {getIcon(n.type)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-start justify-between gap-2">
                        <h3 className={`text-[13px] font-bold leading-tight ${n.is_read ? 'text-[var(--text-main)]' : 'text-[var(--accent-indigo)]'}`}>
                          {n.title}
                        </h3>
                        <span className="text-[10px] text-[var(--text-muted)] whitespace-nowrap mt-0.5">
                          {formatTime(n.created_at)}
                        </span>
                      </div>
                      <p className="text-[12px] text-[var(--text-muted)] mt-1 line-clamp-2">
                        {n.message}
                      </p>
                      <div className="flex items-center gap-3 mt-3 opacity-0 group-hover:opacity-100 transition-opacity">
                        {!n.is_read && (
                          <button 
                            onClick={() => markAsRead(n._id)}
                            className="text-[11px] font-bold text-[var(--accent-indigo)] hover:underline"
                          >
                            Mark as read
                          </button>
                        )}
                        <button 
                          onClick={() => deleteNotification(n._id)}
                          className="text-[11px] font-bold text-[var(--accent-red)] hover:underline"
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  </div>
                  {!n.is_read && (
                    <div className="absolute top-4 right-4 w-2 h-2 rounded-full bg-[var(--accent-indigo)] shadow-[0_0_10px_rgba(var(--accent-indigo-rgb),0.5)]"></div>
                  )}
                </div>
              ))
            )}
          </div>

          {/* Footer */}
          {notifications.length > 0 && (
            <div className="p-4 border-t border-[var(--border)] bg-[var(--bg-main)]/50 backdrop-blur-md">
              <button 
                onClick={markAllRead}
                className="w-full py-2.5 bg-[var(--accent-indigo)] text-white text-sm font-bold rounded-xl shadow-lg shadow-indigo-500/20 hover:scale-[1.02] active:scale-[0.98] transition-all"
              >
                Mark All as Read
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  );
};

export default NotificationDrawer;
