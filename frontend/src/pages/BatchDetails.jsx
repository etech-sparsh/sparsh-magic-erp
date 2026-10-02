import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../services/api';
import Modal from '../components/common/Modal';
import { useNotification } from '../context/NotificationContext';
import {  AnimatePresence , motion } from 'framer-motion';
import {
  ArrowLeft, Layers, Package, Calendar, FileText,
  Pencil, Trash2, Save, X, CheckCircle2, PauseCircle,
  PlayCircle, ChevronDown, Building2, Plus, XCircle,
  AlertTriangle, GitMerge, ExternalLink, ArrowRightLeft,
  LayoutGrid, List, Clock, Bot
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

const statusConfig = {
  active: { bg: 'var(--status-active-bg)', text: 'var(--status-active-text)', border: 'var(--status-active-border)', icon: PlayCircle, label: 'Active' },
  completed: { bg: 'var(--accent-indigo-bg)', text: 'var(--accent-indigo)', border: 'var(--accent-indigo-border)', icon: CheckCircle2, label: 'Completed' },
  paused: { bg: 'var(--accent-yellow-bg)', text: 'var(--accent-yellow)', border: 'var(--accent-yellow-border)', icon: PauseCircle, label: 'Paused' },
};

const InfoRow = ({ icon: Icon, label, value, color }) => (
  <div className="flex items-start gap-3 py-2">
    <div className="p-2 rounded-lg" style={{ background: `var(--accent-${color || 'indigo'}-bg)` }}>
      <Icon size={14} style={{ color: `var(--accent-${color || 'indigo'})` }} />
    </div>
    <div className="flex flex-col">
      <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">{label}</span>
      <span className="text-[13px] font-medium text-[var(--text-main)]">{value || '—'}</span>
    </div>
  </div>
);

const BatchDetails = () => {
  const { batchId } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();

  const [batch, setBatch] = useState(null);
  const [batchCompanies, setBatchCompanies] = useState([]);
  const [quarters, setQuarters] = useState([]);
  const [allCompanies, setAllCompanies] = useState([]);
  const [allBatches, setAllBatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('companies');

  const [editMode, setEditMode] = useState(false);
  const [editData, setEditData] = useState({});
  const [statusDropdown, setStatusDropdown] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [gptProjects, setGptProjects] = useState([]);
  const [showAddCompany, setShowAddCompany] = useState(false);
  const [showMerge, setShowMerge] = useState(false);
  const [showShift, setShowShift] = useState(false);
  const [showCreateQuarter, setShowCreateQuarter] = useState(false);

  const [selectedCompanies, setSelectedCompanies] = useState([]);
  const [mergeBatchId, setMergeBatchId] = useState('');
  const [deleteSource, setDeleteSource] = useState(false);
  const [shiftingCompany, setShiftingCompany] = useState(null);
  const [targetShiftBatchId, setTargetShiftBatchId] = useState('');

  const [quarterForm, setQuarterForm] = useState({
    name: '', description: '', start_date: '', target_end_date: ''
  });

  const canUpdate = user?.role === 'superadmin' || user?.permissions?.batches?.update;
  const canDelete = user?.role === 'superadmin' || user?.permissions?.batches?.delete;
  const canCreateQuarter = user?.role === 'superadmin' || user?.permissions?.batches?.create; // or specific quarter perm if added later
  const canReadCompanies = user?.role === 'superadmin' || user?.permissions?.companies?.read;
  const canReadBatches = user?.role === 'superadmin' || user?.permissions?.batches?.read;

  const fetchData = async () => {
    try {
      const promises = [
        api.get(`/batches/${batchId}`),
        api.get(`/batches/${batchId}/companies`),
        api.get(`/quarters?batch_id=${batchId}`),
      ];

      // Only fetch global lists if the user has permission to use them (for merge/shift/add)
      if (canReadCompanies && canUpdate) promises.push(api.get('/companies'));
      else promises.push(Promise.resolve({ data: [] }));

      if (canUpdate) promises.push(api.get('/gpt/projects'));
      else promises.push(Promise.resolve({ data: [] }));

      if (canReadBatches && canUpdate) promises.push(api.get('/batches'));
      else promises.push(Promise.resolve({ data: [] }));

      const [res, compRes, quartersRes, allCompRes, gptRes, allBatchRes] = await Promise.all(promises);
      
      setBatch(res.data);
      setEditData(res.data);
      setBatchCompanies(compRes.data);
      setQuarters(quartersRes.data);
      setAllCompanies(allCompRes.data);
      setGptProjects(gptRes.data);
      setAllBatches(allBatchRes.data.filter(b => b._id !== batchId));
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchData(); }, [batchId]);

  const handleSaveEdit = async () => {
    try {
      const { _id, created_at, companies, company_count, status, ...fields } = editData;
      await api.put(`/batches/${batchId}`, fields);
      setEditMode(false);
      showSuccess('Batch details updated successfully');
      fetchData();
    } catch (err) { 
      const detail = err.response?.data?.detail;
      const msg = Array.isArray(detail) ? detail.map(d => `${d.loc.join('.')}: ${d.msg}`).join(', ') : (detail || 'Update failed');
      showError(msg); 
    }
  };

  const handleStatusChange = async (newStatus) => {
    try {
      await api.patch(`/batches/${batchId}/status`, { status: newStatus });
      setStatusDropdown(false);
      showSuccess(`Batch status changed to ${newStatus}`);
      fetchData();
    } catch (err) { showError('Status change failed'); }
  };

  const handleDelete = async () => {
    try {
      await api.delete(`/batches/${batchId}`);
      showSuccess('Batch deleted successfully');
      navigate('/batches');
    } catch (err) { showError('Delete failed'); }
  };

  const handleAddCompanies = async () => {
    if (selectedCompanies.length === 0) return;
    try {
      await api.post(`/batches/${batchId}/companies`, selectedCompanies);
      setShowAddCompany(false);
      setSelectedCompanies([]);
      showSuccess(`${selectedCompanies.length} companies added to batch`);
      fetchData();
    } catch (err) { showError('Failed to add companies'); }
  };

  const handleRemoveCompany = async (companyId) => {
    try {
      await api.delete(`/batches/${batchId}/companies/${companyId}`);
      showSuccess('Company removed from batch');
      fetchData();
    } catch (err) { showError('Failed to remove company'); }
  };

  const handleMerge = async () => {
    if (!mergeBatchId) return;
    try {
      const res = await api.post(`/batches/${batchId}/merge`, {
        source_batch_id: mergeBatchId,
        delete_source: deleteSource
      });
      showSuccess(res.data.message || 'Batches merged successfully');
      setShowMerge(false);
      setMergeBatchId('');
      setDeleteSource(false);
      fetchData();
    } catch (err) { showError('Merge failed'); }
  };

  const handleShift = async () => {
    if (!targetShiftBatchId || !shiftingCompany) return;
    try {
      await api.post(`/batches/${batchId}/companies/${shiftingCompany._id}/shift`, {
        target_batch_id: targetShiftBatchId
      });
      showSuccess(`Shifted ${shiftingCompany.name} to new batch`);
      setShowShift(false);
      setShiftingCompany(null);
      setTargetShiftBatchId('');
      fetchData();
    } catch (err) { showError('Shift failed'); }
  };

  const handleCreateQuarter = async (e) => {
    e.preventDefault();
    try {
      await api.post('/quarters', { ...quarterForm, batch_id: batchId });
      setShowCreateQuarter(false);
      showSuccess('Quarter created successfully');
      setQuarterForm({ name: '', description: '', start_date: '', target_end_date: '' });
      fetchData();
    } catch (err) { showError('Failed to create quarter'); }
  };

  const toggleCompanySelection = (cid) => {
    setSelectedCompanies(prev =>
      prev.includes(cid) ? prev.filter(id => id !== cid) : [...prev, cid]
    );
  };

  const availableCompanies = allCompanies.filter(
    c => !batch?.companies?.includes(c._id)
  );

  if (loading) return (
    <div className="flex items-center justify-center py-32">
      <div className="w-8 h-8 border-2 border-[var(--accent-indigo-border)] border-t-[var(--accent-indigo)] rounded-full animate-spin"></div>
    </div>
  );

  if (!batch) return <div className="text-center py-20 text-[var(--text-muted)]">Batch not found</div>;

  const sc = statusConfig[batch.status] || statusConfig.active;
  const StatusIcon = sc.icon;

  return (
    <div className="space-y-6">
      {/* ─── Header ─── */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-4">
          <button onClick={() => navigate('/batches')} className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--accent-indigo-bg)] hover:text-[var(--accent-indigo)] transition-all">
            <ArrowLeft size={18} />
          </button>
          <div className="w-11 h-11 bg-[var(--accent-indigo-bg)] rounded-xl flex items-center justify-center text-[var(--accent-indigo)]">
            <Layers size={22} />
          </div>
          <div>
            <h1 className="text-xl font-bold text-[var(--text-main)] tracking-tight">{batch.name}</h1>
            <p className="text-[12px] text-[var(--accent-orange)] font-bold">{batch.product_name || 'No Product'}</p>
          </div>
          <span className="px-2.5 py-1 rounded-md text-[11px] font-bold inline-flex items-center gap-1.5 uppercase tracking-wider" style={{ background: sc.bg, color: sc.text, border: `1px solid ${sc.border}` }}>
            <StatusIcon size={12} /> {sc.label}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {canUpdate && (
            <>
              <button onClick={() => setEditMode(!editMode)} className="h-9 px-4 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-muted)] rounded-lg text-[12px] font-bold flex items-center gap-2 hover:border-[var(--accent-indigo)] hover:text-[var(--accent-indigo)] transition-all">
                <Pencil size={14} /> Edit
              </button>
              <button onClick={() => setShowMerge(true)} className="h-9 px-4 bg-[var(--accent-orange-bg)] border border-[var(--accent-orange-border)] text-[var(--accent-orange)] rounded-lg text-[12px] font-bold flex items-center gap-2 hover:opacity-80 transition-all">
                <GitMerge size={14} /> Merge
              </button>
              <div className="relative">
                <button onClick={() => setStatusDropdown(!statusDropdown)} className="h-9 px-4 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-muted)] rounded-lg text-[12px] font-bold flex items-center gap-2 hover:border-[var(--accent-orange)] hover:text-[var(--accent-orange)] transition-all">
                  Status <ChevronDown size={12} />
                </button>
                {statusDropdown && (
                  <div className="absolute right-0 top-11 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg shadow-lg z-50 min-w-[140px] py-1">
                    {['active', 'completed', 'paused'].map(s => (
                      <button key={s} onClick={() => handleStatusChange(s)} className="w-full px-4 py-2 text-left text-[12px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] capitalize transition-all">{s}</button>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
          {canDelete && (
            <button onClick={() => setShowDeleteConfirm(true)} className="h-9 px-4 bg-[var(--accent-red-bg)] border border-[var(--accent-red-border)] text-[var(--accent-red)] rounded-lg text-[12px] font-bold flex items-center gap-2 hover:opacity-80 transition-all">
              <Trash2 size={14} /> Delete
            </button>
          )}
        </div>
      </div>

      {/* ─── Edit Panel ─── */}
      <AnimatePresence>
        {editMode && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="bg-[var(--bg-card)] border border-[var(--accent-indigo-border)] rounded-xl p-6 overflow-hidden">
            <h3 className="text-[14px] font-bold text-[var(--text-main)] mb-4">Edit Batch</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {[
                { key: 'name', label: 'Batch Name' },
                { key: 'product_name', label: 'Product Name' },
                { key: 'description', label: 'Description' },
                { key: 'start_date', label: 'Start Date', type: 'date' },
                { key: 'target_end_date', label: 'Target End Date', type: 'date' },
              ].map(f => (
                <div key={f.key} className="space-y-1">
                  <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">{f.label}</label>
                  <input type={f.type || 'text'} value={editData[f.key] || ''} onChange={e => setEditData({ ...editData, [f.key]: e.target.value })}
                    className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md outline-none text-[13px] font-medium text-[var(--text-main)] focus:border-[var(--accent-indigo)]" />
                </div>
              ))}
              <div className="space-y-1">
                <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Linked GPT Projects</label>
                <div className="flex flex-wrap gap-2 mb-2">
                  {(editData.gpt_projects || []).map(p => (
                    <div key={p.id} className="flex items-center gap-2 px-2 py-1 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] rounded-md text-[11px] font-bold">
                      {p.title}
                      <button onClick={() => setEditData({ ...editData, gpt_projects: editData.gpt_projects.filter(x => x.id !== p.id) })}>
                        <X size={12} />
                      </button>
                    </div>
                  ))}
                </div>
                <select
                  value=""
                  onChange={e => {
                    const selected = gptProjects.find(p => p.id === e.target.value);
                    if (selected && !(editData.gpt_projects || []).some(x => x.id === selected.id)) {
                      setEditData({ ...editData, gpt_projects: [...(editData.gpt_projects || []), { id: selected.id, title: selected.title }] });
                    }
                  }}
                  className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md outline-none text-[13px] font-medium text-[var(--text-main)] focus:border-[var(--accent-indigo)]"
                >
                  <option value="">Add GPT Project...</option>
                  {gptProjects.filter(p => !(editData.gpt_projects || []).some(x => x.id === p.id)).map(p => (
                    <option key={p.id} value={p.id}>{p.title}</option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex gap-3 mt-6">
              <button onClick={handleSaveEdit} className="h-9 px-6 bg-[var(--accent-green)] text-white rounded-lg text-[12px] font-bold flex items-center gap-2"><Save size={14} /> Save</button>
              <button onClick={() => { setEditMode(false); setEditData(batch); }} className="h-9 px-6 bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] rounded-lg text-[12px] font-bold flex items-center gap-2"><X size={14} /> Cancel</button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ─── Batch Details Card ─── */}
      {!editMode && (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-6">
          <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-x-8 gap-y-1">
            <InfoRow icon={Layers} label="Batch Name" value={batch.name} color="indigo" />
            <InfoRow icon={Package} label="Product" value={batch.product_name} color="orange" />
            <InfoRow icon={FileText} label="Description" value={batch.description} color="green" />
            <InfoRow icon={Calendar} label="Start Date" value={batch.start_date} color="yellow" />
            <InfoRow icon={Calendar} label="Target End" value={batch.target_end_date} color="red" />
            <div className="flex items-start gap-3 py-2">
              <div className="p-2 rounded-lg" style={{ background: `var(--accent-indigo-bg)` }}>
                <Bot size={14} style={{ color: `var(--accent-indigo)` }} />
              </div>
              <div className="flex flex-col">
                <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Linked GPT Projects</span>
                <div className="flex flex-wrap gap-1 mt-1">
                  {(batch.gpt_projects || []).length > 0 ? (batch.gpt_projects || []).map(p => (
                    <span key={p.id} className="text-[11px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] px-1.5 py-0.5 rounded shadow-sm border border-[var(--accent-indigo-border)]">
                      {p.title}
                    </span>
                  )) : <span className="text-[12px] font-medium text-[var(--text-main)]">None</span>}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ─── Tabs ─── */}
      <div className="flex gap-1 bg-[var(--bg-card)] border border-[var(--border)] p-1 rounded-xl w-fit shadow-sm">
        <button onClick={() => setActiveTab('companies')} className={`px-5 py-2.5 rounded-lg text-[12px] font-bold transition-all flex items-center gap-2 ${activeTab === 'companies' ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shadow-sm' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}>
          <Building2 size={15} /> Companies in Batch
        </button>
        <button onClick={() => setActiveTab('quarters')} className={`px-5 py-2.5 rounded-lg text-[12px] font-bold transition-all flex items-center gap-2 ${activeTab === 'quarters' ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shadow-sm' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}>
          <Clock size={15} /> Batch Quarters
        </button>
      </div>

      <AnimatePresence mode="wait">
        {activeTab === 'companies' ? (
          <motion.div key="companies" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl overflow-hidden shadow-sm">
            <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
              <div>
                <h3 className="text-[14px] font-bold text-[var(--text-main)]">Assigned Companies</h3>
                <p className="text-[11px] text-[var(--text-muted)]">{batchCompanies.length} companies participating</p>
              </div>
              {canUpdate && (
                <button onClick={() => { setShowAddCompany(true); setSelectedCompanies([]); }} className="h-8 px-3 bg-[var(--btn-primary)] text-white rounded-lg text-[11px] font-bold flex items-center gap-1.5 hover:bg-[var(--btn-primary-hover)] transition-all">
                  <Plus size={12} /> Add Companies
                </button>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                    <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Company</th>
                    <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Industry</th>
                    <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Owner</th>
                    <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Status</th>
                    <th className="px-5 py-3 text-right text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border)]">
                  {batchCompanies.map(c => (
                    <tr key={c._id} className="hover:bg-[var(--table-hover)] transition-all">
                      <td className="px-5 py-2.5">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 bg-[var(--accent-indigo-bg)] rounded-md flex items-center justify-center text-[var(--accent-indigo)]"><Building2 size={14} /></div>
                          <div>
                            <span className="text-[13px] font-bold text-[var(--text-main)] block">{c.name}</span>
                            <span className="text-[10px] text-[var(--text-muted)]">{c.domain || ''}</span>
                          </div>
                        </div>
                      </td>
                      <td className="px-5 py-2.5 text-[12px] text-[var(--text-muted)]">{c.company_type || '—'}</td>
                      <td className="px-5 py-2.5 text-[12px] text-[var(--text-muted)]">{c.owner || '—'}</td>
                      <td className="px-5 py-2.5">
                        <span className={`px-2 py-0.5 rounded-md text-[10px] font-bold ${c.status === 'active' ? 'bg-[var(--status-active-bg)] text-[var(--status-active-text)]' : 'bg-[var(--accent-yellow-bg)] text-[var(--accent-yellow)]'}`}>
                          {c.status || 'active'}
                        </span>
                      </td>
                      <td className="px-5 py-2.5 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <button onClick={() => navigate(`/companies/${c._id}`)} className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] rounded-md transition-all" title="View Company"><ExternalLink size={14} /></button>
                          {canUpdate && (
                            <>
                              <button onClick={() => { setShiftingCompany(c); setShowShift(true); }} className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-orange)] hover:bg-[var(--accent-orange-bg)] rounded-md transition-all" title="Shift to another batch"><ArrowRightLeft size={14} /></button>
                              <button onClick={() => handleRemoveCompany(c._id)} className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-red)] hover:bg-[var(--accent-red-bg)] rounded-md transition-all" title="Remove"><XCircle size={14} /></button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {batchCompanies.length === 0 && (
                    <tr><td colSpan={5} className="px-5 py-12 text-center text-[var(--text-muted)] text-[13px]">No companies assigned yet.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </motion.div>
        ) : (
          <motion.div key="quarters" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl overflow-hidden shadow-sm">
            <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
              <div>
                <h3 className="text-[14px] font-bold text-[var(--text-main)]">Batch Quarters</h3>
                <p className="text-[11px] text-[var(--text-muted)]">{quarters.length} active or scheduled quarters</p>
              </div>
              {canCreateQuarter && (
                <button onClick={() => setShowCreateQuarter(true)} className="h-8 px-3 bg-[var(--btn-primary)] text-white rounded-lg text-[11px] font-bold flex items-center gap-1.5 hover:bg-[var(--btn-primary-hover)] transition-all">
                  <Plus size={12} /> Create Quarter
                </button>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                    <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Quarter Name</th>
                    <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Dates</th>
                    <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Status</th>
                    <th className="px-5 py-3 text-right text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border)]">
                  {quarters.map(q => (
                    <tr key={q._id} className="hover:bg-[var(--table-hover)] transition-all">
                      <td className="px-5 py-2.5">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 bg-[var(--accent-orange-bg)] rounded-md flex items-center justify-center text-[var(--accent-orange)]"><Clock size={14} /></div>
                          <div>
                            <span className="text-[13px] font-bold text-[var(--text-main)] block">{q.name}</span>
                            {q.description && <span className="text-[10px] text-[var(--text-muted)] truncate max-w-[200px] block">{q.description}</span>}
                          </div>
                        </div>
                      </td>
                      <td className="px-5 py-2.5 text-[12px] text-[var(--text-muted)]">
                        {q.start_date || '—'} → {q.target_end_date || '—'}
                      </td>
                      <td className="px-5 py-2.5">
                        <span className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-[var(--status-active-bg)] text-[var(--status-active-text)]">
                          {q.status || 'active'}
                        </span>
                      </td>
                      <td className="px-5 py-2.5 text-right">
                        <button onClick={() => navigate(`/quarters/${q._id}`)} className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] rounded-md transition-all" title="View Inside Quarter">
                          <ExternalLink size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {quarters.length === 0 && (
                    <tr><td colSpan={4} className="px-5 py-12 text-center text-[var(--text-muted)] text-[13px]">No quarters created yet.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ─── Selection Modals (Companies/Merge/Shift/etc) ─── */}
      <Modal isOpen={showAddCompany} onClose={() => setShowAddCompany(false)} title="Add Companies to Batch">
        <div className="space-y-4 px-1">
          <p className="text-[12px] text-[var(--text-muted)]">Select companies to add to <strong>{batch.name}</strong></p>
          <div className="max-h-[300px] overflow-y-auto space-y-2 pr-1">
            {availableCompanies.length > 0 ? availableCompanies.map(c => (
              <label key={c._id} className={`flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-all border ${selectedCompanies.includes(c._id) ? 'bg-[var(--accent-indigo-bg)] border-[var(--accent-indigo-border)]' : 'bg-[var(--input-bg)] border-transparent hover:border-[var(--border)]'
                }`}>
                <input type="checkbox" checked={selectedCompanies.includes(c._id)} onChange={() => toggleCompanySelection(c._id)}
                  className="w-4 h-4 rounded accent-[var(--accent-indigo)]" />
                <div className="w-8 h-8 bg-[var(--accent-indigo-bg)] rounded-md flex items-center justify-center text-[var(--accent-indigo)]"><Building2 size={14} /></div>
                <div className="flex-1">
                  <span className="text-[13px] font-bold text-[var(--text-main)] block">{c.name}</span>
                  <span className="text-[10px] text-[var(--text-muted)]">{c.owner || ''} · {c.company_type || ''}</span>
                </div>
              </label>
            )) : (
              <p className="text-[13px] text-[var(--text-muted)] text-center py-8">All companies are already in this batch.</p>
            )}
          </div>
          {availableCompanies.length > 0 && (
            <button onClick={handleAddCompanies} disabled={selectedCompanies.length === 0}
              className={`w-full py-2 rounded-lg text-[13px] font-bold transition-all ${selectedCompanies.length > 0 ? 'bg-[var(--btn-primary)] text-white hover:bg-[var(--btn-primary-hover)]' : 'bg-[var(--input-bg)] text-[var(--text-muted)] cursor-not-allowed'
                }`}>
              Add {selectedCompanies.length} {selectedCompanies.length === 1 ? 'Company' : 'Companies'}
            </button>
          )}
        </div>
      </Modal>

      <Modal isOpen={showMerge} onClose={() => setShowMerge(false)} title="Merge Batch">
        <div className="space-y-4 px-1">
          <div className="p-3 bg-[var(--accent-orange-bg)] border border-[var(--accent-orange-border)] rounded-lg">
            <p className="text-[12px] font-bold text-[var(--accent-orange)]">
              <GitMerge size={14} className="inline mr-2" />
              Merge will combine all companies from selected batch into "{batch.name}".
            </p>
          </div>
          <div className="space-y-1">
            <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Source Batch (merge from)</label>
            <select className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none"
              value={mergeBatchId} onChange={e => setMergeBatchId(e.target.value)}>
              <option value="">Select Batch</option>
              {allBatches.map(b => (
                <option key={b._id} value={b._id}>{b.name} ({b.company_count || 0} companies)</option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-3 p-3 bg-[var(--input-bg)] rounded-lg cursor-pointer">
            <input type="checkbox" checked={deleteSource} onChange={e => setDeleteSource(e.target.checked)} className="w-4 h-4 rounded accent-[var(--accent-red)]" />
            <div>
              <span className="text-[13px] font-bold text-[var(--text-main)] block">Delete source batch after merge</span>
              <span className="text-[10px] text-[var(--text-muted)]">Source batch will be permanently removed</span>
            </div>
          </label>
          <button onClick={handleMerge} disabled={!mergeBatchId}
            className={`w-full py-2 rounded-lg text-[13px] font-bold transition-all ${mergeBatchId ? 'bg-[var(--accent-orange)] text-white hover:opacity-90' : 'bg-[var(--input-bg)] text-[var(--text-muted)] cursor-not-allowed'
              }`}>
            <GitMerge size={14} className="inline mr-2" /> Merge Batches
          </button>
        </div>
      </Modal>

      <Modal isOpen={showDeleteConfirm} onClose={() => setShowDeleteConfirm(false)} title="Delete Batch">
        <div className="space-y-4 text-center py-4">
          <div className="w-16 h-16 bg-[var(--accent-red-bg)] rounded-xl mx-auto flex items-center justify-center">
            <AlertTriangle size={32} className="text-[var(--accent-red)]" />
          </div>
          <p className="text-[14px] font-bold text-[var(--text-main)]">Delete "{batch.name}"?</p>
          <p className="text-[12px] text-[var(--text-muted)]">This will permanently remove the batch. Assigned companies will not be deleted.</p>
          <div className="flex gap-3 justify-center pt-2">
            <button onClick={() => setShowDeleteConfirm(false)} className="px-6 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[13px] font-bold text-[var(--text-muted)]">Cancel</button>
            <button onClick={handleDelete} className="px-6 py-2 bg-[var(--accent-red)] text-white rounded-lg text-[13px] font-bold hover:opacity-90 transition-all">Delete Permanently</button>
          </div>
        </div>
      </Modal>

      <Modal isOpen={showShift} onClose={() => { setShowShift(false); setShiftingCompany(null); }} title="Shift Company">
        <div className="space-y-4 px-1">
          <div className="p-3 bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] rounded-lg">
            <p className="text-[12px] font-bold text-[var(--accent-indigo)]">
              <ArrowRightLeft size={14} className="inline mr-2" />
              Shift <strong>{shiftingCompany?.name}</strong> to another batch.
            </p>
          </div>
          <div className="space-y-1">
            <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Select Destination Batch</label>
            <select className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none"
              value={targetShiftBatchId} onChange={e => setTargetShiftBatchId(e.target.value)}>
              <option value="">Select Batch</option>
              {allBatches.map(b => (
                <option key={b._id} value={b._id}>{b.name} ({b.product_name})</option>
              ))}
            </select>
          </div>
          <button onClick={handleShift} disabled={!targetShiftBatchId}
            className={`w-full py-2 rounded-lg text-[13px] font-bold transition-all ${targetShiftBatchId ? 'bg-[var(--btn-primary)] text-white hover:bg-[var(--btn-primary-hover)]' : 'bg-[var(--input-bg)] text-[var(--text-muted)] cursor-not-allowed'
              }`}>
            Confirm Shift
          </button>
        </div>
      </Modal>

      {/* ─── Create Quarter Modal ─── */}
      <Modal isOpen={showCreateQuarter} onClose={() => setShowCreateQuarter(false)} title="Create New Quarter">
        <form onSubmit={handleCreateQuarter} className="space-y-4 px-1">
          <div className="space-y-1">
            <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Quarter Name *</label>
            <input required placeholder="e.g. Quarter 1 / Phase 2" className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none focus:border-[var(--accent-indigo)]"
              value={quarterForm.name} onChange={e => setQuarterForm({ ...quarterForm, name: e.target.value })} />
          </div>
          <div className="space-y-1">
            <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Quarter Description</label>
            <textarea rows={2} placeholder="Focus areas for this quarter..." className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none resize-none"
              value={quarterForm.description} onChange={e => setQuarterForm({ ...quarterForm, description: e.target.value })} />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Start Date</label>
              <input type="date" className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none"
                value={quarterForm.start_date} onChange={e => setQuarterForm({ ...quarterForm, start_date: e.target.value })} />
            </div>
            <div className="space-y-1">
              <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Target End Date</label>
              <input type="date" className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none"
                value={quarterForm.target_end_date} onChange={e => setQuarterForm({ ...quarterForm, target_end_date: e.target.value })} />
            </div>
          </div>
          <div className="p-3 bg-[var(--status-active-bg)] border border-[var(--status-active-border)] rounded-lg">
            <p className="text-[11px] font-bold text-[var(--status-active-text)]">Status will be set to "Active" by default.</p>
          </div>
          <button type="submit" className="w-full py-2 bg-[var(--btn-primary)] text-white rounded-lg text-[13px] font-bold hover:bg-[var(--btn-primary-hover)] transition-all">Create Quarter</button>
        </form>
      </Modal>
    </div>
  );
};

export default BatchDetails;
