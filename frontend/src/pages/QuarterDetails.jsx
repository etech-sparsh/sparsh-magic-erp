import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../services/api';
import Modal from '../components/common/Modal';
import { useNotification } from '../context/NotificationContext';
import {  AnimatePresence , motion } from 'framer-motion';
import {
  ArrowLeft, Clock, FileText, Calendar,
  Pencil, Trash2, Save, X, CheckCircle2, PauseCircle,
  PlayCircle, ChevronDown, Plus, AlertTriangle,
  LayoutDashboard, TrendingUp, Users, Target, Eye, Bot
} from 'lucide-react';

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

const StatCard = ({ icon: Icon, label, value, color }) => (
  <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4 flex items-center gap-3">
    <div className="p-2.5 rounded-lg" style={{ background: `var(--accent-${color}-bg)` }}>
      <Icon size={18} style={{ color: `var(--accent-${color})` }} />
    </div>
    <div>
      <p className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider">{label}</p>
      <p className="text-lg font-black text-[var(--text-main)] leading-none mt-1">{value}</p>
    </div>
  </div>
);

const QuarterDetails = () => {
  const { quarterId } = useParams();
  const navigate = useNavigate();
  const { showSuccess, showError } = useNotification();

  const [quarter, setQuarter] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [analytics, setAnalytics] = useState({
    total_sessions: 0,
    avg_attendance: "0%",
    active_companies: 0,
    tasks_done: "0%"
  });
  const [editMode, setEditMode] = useState(false);
  const [editData, setEditData] = useState({});
  const [statusDropdown, setStatusDropdown] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [gptProjects, setGptProjects] = useState([]);

  const fetchData = async () => {
    try {
      const [res, evRes, gptRes, anaRes] = await Promise.all([
        api.get(`/quarters/${quarterId}`),
        api.get('/calendar/events?view_mode=team'),
        api.get('/gpt/projects'),
        api.get(`/quarters/${quarterId}/analytics`)
      ]);
      setQuarter(res.data);
      setEditData(res.data);
      setGptProjects(gptRes.data);
      setAnalytics(anaRes.data);

      const quarterSessions = evRes.data.filter(e =>
        e.extendedProps?.quarter_id === quarterId && e.type === 'event'
      );
      setSessions(quarterSessions);
    } catch (err) { console.error(err); }
    finally { setLoading(false); }
  };

  useEffect(() => { fetchData(); }, [quarterId]);

  const handleSaveEdit = async () => {
    try {
      const { _id, created_at, status, batch_id, ...fields } = editData;
      await api.put(`/quarters/${quarterId}`, fields);
      setEditMode(false);
      showSuccess("Quarter details updated");
      fetchData();
    } catch (err) { 
      const detail = err.response?.data?.detail;
      const msg = Array.isArray(detail) ? detail.map(d => `${d.loc.join('.')}: ${d.msg}`).join(', ') : (detail || 'Update failed');
      showError(msg); 
    }
  };

  const handleStatusChange = async (newStatus) => {
    try {
      await api.put(`/quarters/${quarterId}`, { status: newStatus });
      setStatusDropdown(false);
      showSuccess(`Quarter status changed to ${newStatus}`);
      fetchData();
    } catch (err) { showError('Status change failed'); }
  };

  const handleDelete = async () => {
    try {
      await api.delete(`/quarters/${quarterId}`);
      showSuccess("Quarter deleted successfully");
      navigate(-1);
    } catch (err) { showError('Delete failed'); }
  };

  if (loading) return (
    <div className="flex items-center justify-center py-32">
      <div className="w-8 h-8 border-2 border-[var(--accent-indigo-border)] border-t-[var(--accent-indigo)] rounded-full animate-spin"></div>
    </div>
  );

  if (!quarter) return <div className="text-center py-20 text-[var(--text-muted)]">Quarter not found</div>;

  const sc = statusConfig[quarter.status] || statusConfig.active;
  const StatusIcon = sc.icon;

  return (
    <div className="space-y-6">
      {/* ─── Header ─── */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-4">
          <button onClick={() => navigate(-1)} className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--accent-indigo-bg)] hover:text-[var(--accent-indigo)] transition-all">
            <ArrowLeft size={18} />
          </button>
          <div className="w-11 h-11 bg-[var(--accent-orange-bg)] rounded-xl flex items-center justify-center text-[var(--accent-orange)]">
            <Clock size={22} />
          </div>
          <div>
            <h1 className="text-xl font-bold text-[var(--text-main)] tracking-tight">{quarter.name}</h1>
            <p className="text-[12px] text-[var(--text-muted)] font-bold">Quarterly Insights & Progress</p>
          </div>
          <span className="px-2.5 py-1 rounded-md text-[11px] font-bold inline-flex items-center gap-1.5 uppercase tracking-wider" style={{ background: sc.bg, color: sc.text, border: `1px solid ${sc.border}` }}>
            <StatusIcon size={12} /> {sc.label}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => setEditMode(!editMode)} className="h-9 px-4 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-muted)] rounded-lg text-[12px] font-bold flex items-center gap-2 hover:border-[var(--accent-indigo)] hover:text-[var(--accent-indigo)] transition-all">
            <Pencil size={14} /> Edit
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
          <button onClick={() => setShowDeleteConfirm(true)} className="h-9 px-4 bg-[var(--accent-red-bg)] border border-[var(--accent-red-border)] text-[var(--accent-red)] rounded-lg text-[12px] font-bold flex items-center gap-2 hover:opacity-80 transition-all">
            <Trash2 size={14} /> Delete
          </button>
        </div>
      </div>

      {/* ─── Edit Panel ─── */}
      <AnimatePresence>
        {editMode && (
          <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="bg-[var(--bg-card)] border border-[var(--accent-indigo-border)] rounded-xl p-6 overflow-hidden shadow-sm">
            <h3 className="text-[14px] font-bold text-[var(--text-main)] mb-4">Edit Quarter Details</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {[
                { key: 'name', label: 'Quarter Name' },
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
              <button onClick={handleSaveEdit} className="h-9 px-6 bg-[var(--accent-green)] text-white rounded-lg text-[12px] font-bold flex items-center gap-2 shadow-sm hover:opacity-90 transition-all"><Save size={14} /> Save Changes</button>
              <button onClick={() => { setEditMode(false); setEditData(quarter); }} className="h-9 px-6 bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] rounded-lg text-[12px] font-bold flex items-center gap-2"><X size={14} /> Cancel</button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ─── Quarter Info Card ─── */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-6 shadow-sm">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-x-8 gap-y-1">
          <InfoRow icon={Clock} label="Quarter Name" value={quarter.name} color="orange" />
          <InfoRow icon={Calendar} label="Start Date" value={quarter.start_date} color="green" />
          <InfoRow icon={Calendar} label="Target End" value={quarter.target_end_date} color="red" />
          <InfoRow icon={FileText} label="Description" value={quarter.description} color="indigo" />
          <div className="flex items-start gap-3 py-2">
            <div className="p-2 rounded-lg" style={{ background: `var(--accent-indigo-bg)` }}>
              <Bot size={14} style={{ color: `var(--accent-indigo)` }} />
            </div>
            <div className="flex flex-col">
              <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Linked GPT Projects</span>
              <div className="flex flex-wrap gap-1 mt-1">
                {(quarter.gpt_projects || []).length > 0 ? (quarter.gpt_projects || []).map(p => (
                  <span key={p.id} className="text-[11px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] px-1.5 py-0.5 rounded shadow-sm border border-[var(--accent-indigo-border)]">
                    {p.title}
                  </span>
                )) : <span className="text-[12px] font-medium text-[var(--text-main)]">None</span>}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ─── Quarter Stats ─── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={LayoutDashboard} label="Total Sessions" value={analytics.total_sessions} color="indigo" />
        <StatCard icon={TrendingUp} label="Avg Attendance" value={analytics.avg_attendance} color="green" />
        <StatCard icon={Users} label="Active Companies" value={analytics.active_companies} color="orange" />
        <StatCard icon={Target} label="Tasks Done" value={analytics.tasks_done} color="red" />
      </div>

      {/* ─── Sessions List ─── */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-6 shadow-sm">
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-lg font-bold text-[var(--text-main)] flex items-center gap-2"><Clock size={16} className="text-[var(--accent-indigo)]" /> Scheduled Sessions</h3>
        </div>

        {sessions.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-[var(--border)] text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-wider bg-[var(--input-bg)]">
                  <th className="p-3 font-medium rounded-tl-lg">Session Title</th>
                  <th className="p-3 font-medium">Date & Time</th>
                  <th className="p-3 font-medium">Status</th>
                  <th className="p-3 font-medium text-right rounded-tr-lg">Action</th>
                </tr>
              </thead>
              <tbody>
                {sessions.map(session => (
                  <tr key={session.id} className="border-b border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors">
                    <td className="p-3 text-[13px] font-bold text-[var(--text-main)]">{session.title}</td>
                    <td className="p-3 text-[12px] font-medium text-[var(--text-muted)]">
                      {new Date(session.start).toLocaleString('en-IN', {
                        timeZone: 'Asia/Kolkata', weekday: 'short', day: 'numeric', month: 'short',
                        hour: '2-digit', minute: '2-digit', hour12: true
                      })}
                    </td>
                    <td className="p-3">
                      <span className={`px-2 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider ${session.extendedProps.status === 'completed' ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]' : 'bg-orange-50 text-orange-600'}`}>
                        {session.extendedProps.status || 'scheduled'}
                      </span>
                    </td>
                    <td className="p-3 text-right">
                      <button onClick={() => navigate(`/sessions/${session.id}`)} className="p-2 text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] rounded-lg transition-all" title="View Session Details">
                        <Eye size={16} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-12 flex flex-col items-center justify-center border border-dashed border-[var(--border)] bg-[var(--input-bg)] rounded-xl opacity-70">
            <Calendar size={28} className="text-[var(--text-muted)] mb-3" />
            <p className="text-[12px] font-bold text-[var(--text-muted)] uppercase">No Sessions Scheduled For This Quarter</p>
          </div>
        )}
      </div>

      {/* ─── Delete Confirm Modal ─── */}
      <Modal isOpen={showDeleteConfirm} onClose={() => setShowDeleteConfirm(false)} title="Delete Quarter">
        <div className="space-y-4 text-center py-4">
          <div className="w-16 h-16 bg-[var(--accent-red-bg)] rounded-xl mx-auto flex items-center justify-center">
            <AlertTriangle size={32} className="text-[var(--accent-red)]" />
          </div>
          <p className="text-[14px] font-bold text-[var(--text-main)]">Delete "{quarter.name}"?</p>
          <p className="text-[12px] text-[var(--text-muted)]">This will permanently remove the quarter and all its specific data.</p>
          <div className="flex gap-3 justify-center pt-2">
            <button onClick={() => setShowDeleteConfirm(false)} className="px-6 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[13px] font-bold text-[var(--text-muted)]">Cancel</button>
            <button onClick={handleDelete} className="px-6 py-2 bg-[var(--accent-red)] text-white rounded-lg text-[13px] font-bold hover:opacity-90 transition-all">Delete Permanently</button>
          </div>
        </div>
      </Modal>
    </div>
  );
};

export default QuarterDetails;
