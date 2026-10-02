import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import Modal from '../components/common/Modal';
import { useNotification } from '../context/NotificationContext';
import {
  Plus, Search, Layers, Calendar,
  LayoutGrid, List, ExternalLink, Clock, CheckCircle2,
  PauseCircle, PlayCircle, Trash2, Package, Building2, X
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { motion } from 'framer-motion';

const statusConfig = {
  active: { bg: 'var(--status-active-bg)', text: 'var(--status-active-text)', border: 'var(--status-active-border)', icon: PlayCircle, label: 'Active' },
  completed: { bg: 'var(--accent-indigo-bg)', text: 'var(--accent-indigo)', border: 'var(--accent-indigo-border)', icon: CheckCircle2, label: 'Completed' },
  paused: { bg: 'var(--accent-yellow-bg)', text: 'var(--accent-yellow)', border: 'var(--accent-yellow-border)', icon: PauseCircle, label: 'Paused' },
};

const BatchManagement = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState('table');
  const [searchTerm, setSearchTerm] = useState('');
  const [showCreate, setShowCreate] = useState(false);

  const isPowerRole = ['superadmin', 'admin', 'coach', 'staff'].includes(user?.role?.toLowerCase());
  const canCreate = isPowerRole || user?.permissions?.batches?.create;
  const canDelete = isPowerRole || user?.permissions?.batches?.delete;
  const _canUpdate = isPowerRole || user?.permissions?.batches?.update;

  const [form, setForm] = useState({
    name: '', product_name: '', description: '', start_date: '', target_end_date: '', gpt_projects: []
  });

  const [gptProjects, setGptProjects] = useState([]);

  const fetchData = async () => {
    try {
      const [res, gptRes] = await Promise.all([
        api.get('/batches'),
        api.get('/gpt/projects')
      ]);
      setBatches(res.data);
      setGptProjects(gptRes.data);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchData(); }, []);

  const filtered = batches.filter(b =>
    b.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    b.product_name?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      // Map IDs to objects {id, title} for backend validation
      const payload = {
        ...form,
        gpt_projects: (form.gpt_projects || []).map(pId => {
          const p = gptProjects.find(px => px.id === pId);
          return { id: pId, title: p?.title || pId };
        })
      };
      await api.post('/batches', payload);
      setShowCreate(false);
      showSuccess('Batch created successfully');
      setForm({ name: '', product_name: '', description: '', start_date: '', target_end_date: '', gpt_projects: [] });
      fetchData();
    } catch (err) {
      const detail = err.response?.data?.detail;
      const msg = Array.isArray(detail) ? detail.map(d => `${d.loc.join('.')}: ${d.msg}`).join(', ') : (detail || 'Failed to create batch');
      showError(msg);
    }
  };

  const handleDelete = async (id) => {
    try {
      await api.delete(`/batches/${id}`);
      showSuccess('Batch deleted successfully');
      fetchData();
    }
    catch { showError('Delete failed'); }
  };

  const activeCount = batches.filter(b => b.status === 'active').length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-main)] tracking-tight">Batches</h1>
          <p className="text-[13px] text-[var(--text-muted)] font-medium">{batches.length} batches · {activeCount} active</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex bg-[var(--bg-card)] border border-[var(--border)] p-0.5 rounded-lg">
            <button onClick={() => setViewMode('card')} className={`p-1.5 rounded-md transition-all ${viewMode === 'card' ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]' : 'text-[var(--text-muted)]'}`}><LayoutGrid size={16} /></button>
            <button onClick={() => setViewMode('table')} className={`p-1.5 rounded-md transition-all ${viewMode === 'table' ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]' : 'text-[var(--text-muted)]'}`}><List size={16} /></button>
          </div>
          {canCreate && (
            <button onClick={() => setShowCreate(true)} className="h-10 px-4 bg-[var(--btn-primary)] hover:bg-[var(--btn-primary-hover)] text-white font-bold text-[13px] rounded-lg flex items-center gap-2 transition-all">
              <Plus size={16} /> New Batch
            </button>
          )}
        </div>
      </div>

      {/* Search */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] p-3 rounded-xl flex items-center gap-4">
        <div className="flex-1 relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input type="text" placeholder="Search by batch or product name..." className="w-full pl-9 pr-4 h-9 bg-[var(--input-bg)] border border-transparent rounded-lg outline-none focus:border-[var(--accent-indigo)] text-[13px] font-medium text-[var(--text-main)] transition-all placeholder:text-[var(--text-muted)]"
            value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} />
        </div>
      </div>

      {/* Loading */}
      {loading ? (
        <div className="py-20 flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-2 border-[var(--accent-indigo-border)] border-t-[var(--accent-indigo)] rounded-full animate-spin"></div>
        </div>
      ) : viewMode === 'card' ? (
        /* Card View */
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {filtered.map(b => {
            const sc = statusConfig[b.status] || statusConfig.active;
            const StatusIcon = sc.icon;
            return (
              <div key={b._id} className="bg-[var(--bg-card)] border border-[var(--border)] p-4 rounded-xl hover:border-[var(--accent-indigo-border)] transition-all group flex flex-col">
                <div className="flex items-start justify-between mb-3">
                  <div className="w-10 h-10 bg-[var(--accent-indigo-bg)] rounded-lg flex items-center justify-center text-[var(--accent-indigo)]"><Layers size={20} /></div>
                  <span className="px-2 py-0.5 rounded-md text-[10px] font-bold inline-flex items-center gap-1" style={{ background: sc.bg, color: sc.text, border: `1px solid ${sc.border}` }}>
                    <StatusIcon size={10} /> {sc.label}
                  </span>
                </div>
                <h3 className="text-[14px] font-bold text-[var(--text-main)] truncate">{b.name}</h3>
                <p className="text-[11px] text-[var(--accent-orange)] font-bold truncate mb-2">{b.product_name || '—'}</p>
                {b.description && <p className="text-[11px] text-[var(--text-muted)] mb-3 line-clamp-2">{b.description}</p>}
                <div className="space-y-1.5 flex-1 mt-auto">
                  <div className="flex items-center gap-2"><Calendar size={11} className="text-[var(--accent-green)]" /><span className="text-[11px] text-[var(--text-muted)]">{b.start_date || 'No start'} → {b.target_end_date || 'No end'}</span></div>
                  <div className="flex items-center gap-2"><Building2 size={11} className="text-[var(--accent-indigo)]" /><span className="text-[11px] text-[var(--text-muted)]">{b.company_count || 0} Companies</span></div>
                </div>
                <button onClick={() => navigate(`/batches/${b._id}`)} className="mt-4 w-full py-2 bg-[var(--input-bg)] hover:bg-[var(--accent-indigo)] hover:text-white border border-[var(--border)] hover:border-transparent rounded-lg text-[11px] font-bold text-[var(--text-muted)] transition-all flex items-center justify-center gap-1.5">
                  View Details <ExternalLink size={11} />
                </button>
              </div>
            );
          })}
          {filtered.length === 0 && (
            <div className="col-span-full py-16 text-center">
              <Layers size={32} className="mx-auto mb-3 text-[var(--text-muted)] opacity-30" />
              <p className="text-[13px] text-[var(--text-muted)]">No batches found.</p>
            </div>
          )}
        </motion.div>
      ) : (
        /* Table View */
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl overflow-x-auto no-scrollbar">
          <table className="w-full min-w-[700px]">
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Batch</th>
                <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Product</th>
                <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Start Date</th>
                <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Target End</th>
                <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Companies</th>
                <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Status</th>
                <th className="px-5 py-3 text-right text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {filtered.map(b => {
                const sc = statusConfig[b.status] || statusConfig.active;
                const StatusIcon = sc.icon;
                return (
                  <tr key={b._id} className="hover:bg-[var(--table-hover)] transition-all">
                    <td className="px-5 py-2.5">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 bg-[var(--accent-indigo-bg)] rounded-md flex items-center justify-center text-[var(--accent-indigo)]"><Layers size={14} /></div>
                        <div>
                          <span className="text-[13px] font-bold text-[var(--text-main)] block">{b.name}</span>
                          {b.description && <span className="text-[10px] text-[var(--text-muted)] truncate max-w-[200px] block">{b.description}</span>}
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-2.5 text-[12px] text-[var(--accent-orange)] font-bold">{b.product_name || '—'}</td>
                    <td className="px-5 py-2.5 text-[12px] text-[var(--text-muted)]">{b.start_date || '—'}</td>
                    <td className="px-5 py-2.5 text-[12px] text-[var(--text-muted)]">{b.target_end_date || '—'}</td>
                    <td className="px-5 py-2.5 text-[12px] font-bold text-[var(--accent-indigo)]">{b.company_count || 0}</td>
                    <td className="px-5 py-2.5">
                      <span className="px-2 py-0.5 rounded-md text-[10px] font-bold inline-flex items-center gap-1" style={{ background: sc.bg, color: sc.text, border: `1px solid ${sc.border}` }}>
                        <StatusIcon size={10} /> {sc.label}
                      </span>
                    </td>
                    <td className="px-5 py-2.5 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => navigate(`/batches/${b._id}`)} className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] rounded-md transition-all" title="View Details"><ExternalLink size={14} /></button>
                        {canDelete && (
                          <button onClick={() => handleDelete(b._id)} className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] rounded-md transition-all" title="Delete"><Trash2 size={14} /></button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
              {filtered.length === 0 && (
                <tr><td colSpan={7} className="px-5 py-16 text-center text-[var(--text-muted)] text-[13px]">No batches found.</td></tr>
              )}
            </tbody>
          </table>
        </motion.div>
      )}

      {/* Create Modal */}
      <Modal isOpen={showCreate} onClose={() => setShowCreate(false)} title="Create New Batch">
        <form onSubmit={handleCreate} className="space-y-4 px-1">
          <div className="space-y-1">
            <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Batch Name *</label>
            <input required className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]"
              value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
          </div>
          <div className="space-y-1">
            <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Product Name *</label>
            <input required className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]"
              value={form.product_name} onChange={e => setForm({ ...form, product_name: e.target.value })} />
          </div>
          <div className="space-y-1">
            <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Description</label>
            <textarea rows={2} className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none resize-none"
              value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Start Date</label>
              <input type="date" className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none"
                value={form.start_date} onChange={e => setForm({ ...form, start_date: e.target.value })} />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Target End Date</label>
              <input type="date" className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none"
                value={form.target_end_date} onChange={e => setForm({ ...form, target_end_date: e.target.value })} />
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Linked Neural Engines (GPT Projects)</label>
            <div className="flex flex-wrap gap-2 mb-2">
              {(form.gpt_projects || []).map(pId => {
                const project = gptProjects.find(px => px.id === pId);
                return (
                  <div key={pId} className="flex items-center gap-2 px-2 py-1 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] rounded-md text-[11px] font-bold border border-[var(--accent-indigo-border)]">
                    {project?.title || pId}
                    <button type="button" onClick={() => setForm({ ...form, gpt_projects: form.gpt_projects.filter(x => x !== pId) })}>
                      <X size={12} />
                    </button>
                  </div>
                );
              })}
            </div>
            <select
              value=""
              onChange={e => {
                const val = e.target.value;
                if (val && !(form.gpt_projects || []).includes(val)) {
                  setForm({ ...form, gpt_projects: [...(form.gpt_projects || []), val] });
                }
              }}
              className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--border)] rounded-md outline-none text-[13px] font-medium text-[var(--text-main)] focus:border-[var(--accent-indigo)]"
            >
              <option value="">Select Project...</option>
              {gptProjects.filter(p => !(form.gpt_projects || []).includes(p.id)).map(p => (
                <option key={p.id} value={p.id}>{p.title}</option>
              ))}
            </select>
          </div>
          <button type="submit" className="w-full py-2 bg-[var(--btn-primary)] text-white rounded-lg text-[13px] font-bold hover:bg-[var(--btn-primary-hover)] transition-all mt-4">Create Batch Architecture</button>
        </form>
      </Modal>
    </div>
  );
};

export default BatchManagement;
