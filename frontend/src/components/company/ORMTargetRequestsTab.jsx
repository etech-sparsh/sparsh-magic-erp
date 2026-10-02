import React, { useState, useEffect } from 'react';
import { Inbox, Check, X, Clock, CheckCircle2, XCircle, ArrowRight, User } from 'lucide-react';
import api from '../../services/api';
import { useNotification } from '../../context/NotificationContext';
import { motion } from 'framer-motion';

const STATUS_META = {
  pending: { label: 'Pending', icon: Clock, cls: 'bg-[var(--accent-yellow-bg)] text-[var(--accent-yellow)] border-[var(--accent-yellow-border)]' },
  approved: { label: 'Approved', icon: CheckCircle2, cls: 'bg-[var(--status-active-bg)] text-[var(--status-active-text)] border-[var(--status-active-border)]' },
  rejected: { label: 'Rejected', icon: XCircle, cls: 'bg-[var(--accent-red-bg)] text-[var(--accent-red)] border-[var(--accent-red-border)]' },
};

const fmt = (v) => {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n.toLocaleString() : '—';
};

const ORMTargetRequestsTab = ({ companyId }) => {
  const { showSuccess, showError } = useNotification();
  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);
  const [filter, setFilter] = useState('pending');

  const fetchRequests = async () => {
    setLoading(true);
    try {
      const res = await api.get('/orm-target-requests', { params: { company_id: companyId } });
      setRequests(res.data.requests || []);
    } catch (err) {
      console.error('Failed to load target requests:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchRequests(); }, [companyId]); // eslint-disable-line react-hooks/exhaustive-deps

  const review = async (id, action) => {
    let note = '';
    if (action === 'reject') {
      note = window.prompt('Optional note for rejecting this request:') || '';
    }
    setBusyId(id);
    try {
      await api.post(`/orm-target-requests/${id}/review`, { action, note });
      showSuccess(action === 'approve' ? 'Request approved and targets updated' : 'Request rejected');
      fetchRequests();
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to update request');
    } finally {
      setBusyId(null);
    }
  };

  const filtered = requests.filter(r => filter === 'all' || r.status === filter);
  const pendingCount = requests.filter(r => r.status === 'pending').length;

  return (
    <motion.div key="orm-requests" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="space-y-5">
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]"><Inbox size={20} /></div>
          <div>
            <h3 className="text-[15px] font-bold text-[var(--text-main)]">ORM Target Change Requests</h3>
            <p className="text-[11px] text-[var(--text-muted)]">Approve or reject out-of-window target changes raised by the client admin</p>
          </div>
        </div>
        <div className="flex gap-1 bg-[var(--input-bg)] p-1 rounded-lg border border-[var(--border)]">
          {[
            { id: 'pending', label: `Pending${pendingCount ? ` (${pendingCount})` : ''}` },
            { id: 'approved', label: 'Approved' },
            { id: 'rejected', label: 'Rejected' },
            { id: 'all', label: 'All' },
          ].map(f => (
            <button
              key={f.id}
              onClick={() => setFilter(f.id)}
              className={`px-3 py-1.5 rounded-md text-[11px] font-bold transition-all ${
                filter === f.id ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]' : 'text-[var(--text-muted)] hover:bg-[var(--bg-card)]'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-[var(--accent-indigo-border)] border-t-[var(--accent-indigo)] rounded-full animate-spin" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl py-16 text-center">
          <Inbox size={34} className="mx-auto mb-3 text-[var(--text-muted)] opacity-40" />
          <p className="text-[13px] font-bold text-[var(--text-muted)]">No {filter === 'all' ? '' : filter} requests.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {filtered.map(req => {
            const meta = STATUS_META[req.status] || STATUS_META.pending;
            const StatusIcon = meta.icon;
            return (
              <div key={req._id} className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl overflow-hidden">
                <div className="flex items-center justify-between px-5 py-3 border-b border-[var(--border)] bg-[var(--input-bg)]/40">
                  <div className="flex items-center gap-3">
                    <span className={`px-2.5 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider inline-flex items-center gap-1.5 border ${meta.cls}`}>
                      <StatusIcon size={12} /> {meta.label}
                    </span>
                    <span className="text-[11px] font-bold text-[var(--text-muted)]">Period: <span className="text-[var(--text-main)]">{req.period}</span></span>
                  </div>
                  <div className="flex items-center gap-1.5 text-[11px] font-medium text-[var(--text-muted)]">
                    <User size={12} /> {req.requested_by_name}
                  </div>
                </div>

                <div className="px-5 py-4 space-y-3">
                  {(req.changes || []).map((c, i) => (
                    <div key={i} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]">
                      <span className="font-bold text-[var(--text-main)]">{c.parameter_name || c.parameter_id} · {c.subsection_name || c.subsection_id}</span>
                      <span className="px-1.5 py-0.5 rounded bg-[var(--input-bg)] text-[var(--text-muted)] text-[10px] font-bold uppercase">{c.field}</span>
                      <span className="inline-flex items-center gap-1.5 font-bold">
                        <span className="text-[var(--text-muted)] line-through">{fmt(c.current_value)}</span>
                        <ArrowRight size={12} className="text-[var(--accent-indigo)]" />
                        <span className="text-[var(--accent-green)]">{fmt(c.requested_value)}</span>
                      </span>
                    </div>
                  ))}
                  {req.reason && (
                    <p className="text-[11px] text-[var(--text-muted)] italic border-l-2 border-[var(--border)] pl-3">"{req.reason}"</p>
                  )}
                  {req.status !== 'pending' && req.reviewed_by_name && (
                    <p className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wide">
                      {req.status} by {req.reviewed_by_name}{req.review_note ? ` — ${req.review_note}` : ''}
                    </p>
                  )}
                </div>

                {req.status === 'pending' && (
                  <div className="px-5 py-3 border-t border-[var(--border)] flex justify-end gap-2">
                    <button
                      onClick={() => review(req._id, 'reject')}
                      disabled={busyId === req._id}
                      className="h-9 px-4 bg-[var(--accent-red-bg)] border border-[var(--accent-red-border)] text-[var(--accent-red)] rounded-lg text-[11px] font-bold flex items-center gap-1.5 hover:opacity-80 transition-all disabled:opacity-40"
                    >
                      <X size={14} /> Reject
                    </button>
                    <button
                      onClick={() => review(req._id, 'approve')}
                      disabled={busyId === req._id}
                      className="h-9 px-4 bg-[var(--accent-green)] text-white rounded-lg text-[11px] font-bold flex items-center gap-1.5 hover:opacity-90 transition-all disabled:opacity-40"
                    >
                      <Check size={14} /> {busyId === req._id ? 'Saving...' : 'Approve & Set'}
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </motion.div>
  );
};

export default ORMTargetRequestsTab;
