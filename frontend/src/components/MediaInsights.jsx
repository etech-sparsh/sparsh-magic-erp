import React, { useState, useEffect } from 'react';
import { BarChart2, HardDrive, FileText, User, RefreshCw, Layers } from 'lucide-react';
import api from '../services/api';
import { useNotification } from '../context/NotificationContext';

const MediaInsights = () => {
  const { showError } = useNotification();
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);

  useEffect(() => {
    const fetchInsights = async () => {
      setLoading(true);
      try {
        const { data: res } = await api.get('/media/ai/insights');
        setData(res.insights);
      } catch (err) {
        console.error(err);
        showError('Failed to load media insights');
      } finally {
        setLoading(false);
      }
    };
    fetchInsights();
  }, [showError]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-12 space-y-3 bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl">
        <RefreshCw size={24} className="animate-spin text-[var(--sidebar-active-bg)]" />
        <p className="text-xs text-[var(--text-muted)]">Analyzing storage and file distribution...</p>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="space-y-6">
      {/* Top Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-[var(--bg-card)] border border-[var(--border)] p-4 rounded-xl flex items-center gap-3">
          <div className="p-3 bg-blue-500/10 text-blue-500 rounded-lg">
            <Layers size={20} />
          </div>
          <div>
            <p className="text-[10px] uppercase font-bold tracking-wider text-[var(--text-muted)]">Total Files</p>
            <p className="text-lg font-bold text-[var(--text-main)] mt-0.5">{data.total_files}</p>
          </div>
        </div>

        <div className="bg-[var(--bg-card)] border border-[var(--border)] p-4 rounded-xl flex items-center gap-3">
          <div className="p-3 bg-emerald-500/10 text-emerald-500 rounded-lg">
            <HardDrive size={20} />
          </div>
          <div>
            <p className="text-[10px] uppercase font-bold tracking-wider text-[var(--text-muted)]">Storage Used</p>
            <p className="text-lg font-bold text-[var(--text-main)] mt-0.5">{data.storage_usage}</p>
          </div>
        </div>

        <div className="bg-[var(--bg-card)] border border-[var(--border)] p-4 rounded-xl flex items-center gap-3">
          <div className="p-3 bg-amber-500/10 text-amber-500 rounded-lg">
            <User size={20} />
          </div>
          <div>
            <p className="text-[10px] uppercase font-bold tracking-wider text-[var(--text-muted)]">Top User</p>
            <p className="text-sm font-bold text-[var(--text-main)] mt-0.5 truncate max-w-[140px]">
              {data.top_users?.[0]?.name || 'N/A'} ({data.top_users?.[0]?.uploads || 0} uploads)
            </p>
          </div>
        </div>

        <div className="bg-[var(--bg-card)] border border-[var(--border)] p-4 rounded-xl flex items-center gap-3">
          <div className="p-3 bg-purple-500/10 text-purple-500 rounded-lg">
            <BarChart2 size={20} />
          </div>
          <div>
            <p className="text-[10px] uppercase font-bold tracking-wider text-[var(--text-muted)]">File Categories</p>
            <p className="text-lg font-bold text-[var(--text-main)] mt-0.5">
              {Object.keys(data.type_distribution || {}).length}
            </p>
          </div>
        </div>
      </div>

      {/* Distribution & Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Type Distribution */}
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-5 space-y-4">
          <h3 className="text-sm font-bold uppercase tracking-wider text-[var(--text-main)]">File Type Distribution</h3>
          <div className="space-y-3.5">
            {Object.entries(data.type_distribution || {}).map(([type, count]) => {
              const percentage = data.total_files > 0 ? Math.round((count / data.total_files) * 100) : 0;
              return (
                <div key={type} className="space-y-1">
                  <div className="flex items-center justify-between text-xs font-semibold text-[var(--text-main)]">
                    <span className="capitalize">{type}</span>
                    <span>{count} file(s) ({percentage}%)</span>
                  </div>
                  <div className="w-full bg-[var(--border)] rounded-full h-2 overflow-hidden">
                    <div
                      style={{ width: `${percentage}%` }}
                      className="bg-[var(--sidebar-active-bg)] h-2 rounded-full"
                    />
                  </div>
                </div>
              );
            })}
            {Object.keys(data.type_distribution || {}).length === 0 && (
              <p className="text-xs text-[var(--text-muted)] text-center py-6">No uploads detected to categorize</p>
            )}
          </div>
        </div>

        {/* Recent Activity */}
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-5 space-y-4">
          <h3 className="text-sm font-bold uppercase tracking-wider text-[var(--text-main)]">Recent Activity</h3>
          <div className="space-y-3">
            {data.recent_activity?.map((act, index) => (
              <div key={index} className="flex items-center gap-3 p-2.5 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl">
                <div className="p-2 bg-[var(--bg-card)] text-[var(--text-muted)] rounded-lg">
                  <FileText size={16} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold text-[var(--text-main)] truncate">{act.name}</p>
                  <p className="text-[10px] text-[var(--text-muted)] capitalize mt-0.5">{act.type}</p>
                </div>
                <span className="text-[10px] text-[var(--text-muted)]">
                  {new Date(act.date).toLocaleDateString()}
                </span>
              </div>
            ))}
            {(!data.recent_activity || data.recent_activity.length === 0) && (
              <p className="text-xs text-[var(--text-muted)] text-center py-6">No recent actions recorded</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default MediaInsights;
