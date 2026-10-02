import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../services/api';
import Modal from '../components/common/Modal';
import { useNotification } from '../context/NotificationContext';
import { motion, AnimatePresence } from 'framer-motion';
import {
  BarChart3, PieChart as PieChartIcon, TrendingUp, Award, Zap,
  Building2, Globe, MapPin, Users, Mail, Phone, Hash, Briefcase,
  ArrowLeft, Pencil, Trash2, Download, Upload, Plus, User, UserCheck, Lock,
  CheckCircle2, XCircle, PauseCircle, ChevronDown, Save, X,
  FileSpreadsheet, AlertTriangle, ExternalLink, Layers, Calendar,
  Target, BookOpen, ChevronRight, CheckCircle, Circle, UploadCloud, FileText, Bot, Inbox
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import ORMReportTab from '../components/company/ORMReportTab';
import ORMTargetRequestsTab from '../components/company/ORMTargetRequestsTab';
import { setHrmsAccess } from '../services/hrmsApi';
import { canToggleHrms, isInternalCompany } from '../features/hrms/access';
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Area, AreaChart, Legend
} from 'recharts';

// ─── Shared Components ───
const StatusBadge = ({ status }) => {
  const config = {
    active:   { bg: 'var(--status-active-bg)',   text: 'var(--status-active-text)',  border: 'var(--status-active-border)', icon: CheckCircle2 },
    hold:     { bg: 'var(--accent-yellow-bg)',    text: 'var(--accent-yellow)',       border: 'var(--accent-yellow-border)', icon: PauseCircle },
    inactive: { bg: 'var(--accent-red-bg)',       text: 'var(--accent-red)',          border: 'var(--accent-red-border)',    icon: XCircle },
  };
  const c = config[status] || config.active;
  const Icon = c.icon;
  return (
    <span className="px-2.5 py-1 rounded-md text-[11px] font-bold inline-flex items-center gap-1.5 uppercase tracking-wider" style={{ background: c.bg, color: c.text, border: `1px solid ${c.border}` }}>
      <Icon size={12} /> {status}
    </span>
  );
};



const InfoRow = ({ icon: Icon, label, value }) => (
  <div className="flex items-start gap-3 py-2">
    <Icon size={14} className="text-[var(--accent-indigo)] mt-0.5 shrink-0" />
    <div className="flex flex-col">
      <span className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">{label}</span>
      <span className="text-[13px] font-medium text-[var(--text-main)]">{value || '—'}</span>
    </div>
  </div>
);

const StatCard = ({ icon: Icon, label, value, sub, color }) => (
  <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-4 flex items-center gap-4 hover:border-[var(--accent-indigo-border)] transition-all">
    <div className="p-3 rounded-xl shrink-0" style={{ background: `var(--accent-${color}-bg)` }}>
      <Icon size={20} style={{ color: `var(--accent-${color})` }} />
    </div>
    <div className="min-w-0">
      <p className="text-2xl font-black text-[var(--text-main)] leading-none">{value}</p>
      <p className="text-[11px] text-[var(--text-muted)] font-bold uppercase tracking-wider mt-1">{label}</p>
      {sub && <p className="text-[10px] text-[var(--accent-green)] font-bold mt-0.5">{sub}</p>}
    </div>
  </div>
);

// ─── Module Access Toggle ───
// The ON/OFF switch used for the company's module flags (ORM, Delegation). One component so
// every module toggle is identical by construction: same pill, same track, same animation —
// only the label and the flag it drives differ.
const ModuleToggle = ({ label, enabled, onToggle, title, disabled = false }) => (
  <button
    type="button"
    role="switch"
    aria-checked={enabled}
    aria-label={`${label} module`}
    onClick={onToggle}
    disabled={disabled}
    title={title}
    className={`h-9 pl-3 pr-2 rounded-lg border flex items-center gap-2.5 transition-all ${
      enabled
        ? 'bg-[var(--accent-green-bg)] border-[var(--accent-green-border)]'
        : 'bg-[var(--bg-card)] border-[var(--border)] hover:border-[var(--accent-green)]'
    } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
  >
    <span className={`text-[11px] font-black uppercase tracking-wider transition-colors ${enabled ? 'text-[var(--accent-green)]' : 'text-[var(--text-muted)]'}`}>
      {label}
    </span>
    {/* Track + sliding knob. The state word sits on the side the knob is NOT on, so it stays
        readable at both ends. */}
    <span className={`relative w-[44px] h-[20px] rounded-full shrink-0 transition-colors duration-300 ${enabled ? 'bg-[var(--accent-green)]' : 'bg-gray-300'}`}>
      <span className={`absolute top-1/2 -translate-y-1/2 text-[8px] font-black uppercase tracking-wider text-white transition-all duration-300 ${enabled ? 'left-[7px]' : 'right-[6px]'}`}>
        {enabled ? 'On' : 'Off'}
      </span>
      <span className={`absolute top-[2px] w-4 h-4 rounded-full bg-white shadow-sm transition-all duration-300 ${enabled ? 'left-[26px]' : 'left-[2px]'}`} />
    </span>
  </button>
);

// ─── Chart Colors ───
const CHART_COLORS = ['#6366f1', '#22c55e', '#f97316', '#eab308', '#ec4899', '#06b6d4'];

// ─── Sample data generators (will use real API data when LMS is built) ───
const generateMonthlyData = (userCount) => {
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'];
  return months.map(m => ({
    name: m,
    sessions: Math.floor(Math.random() * 20 + 5),
    attendance: Math.floor(Math.random() * (userCount || 10) + 3),
    score: Math.floor(Math.random() * 30 + 60),
  }));
};

const generatePieData = (userCount) => [
  { name: 'Core', value: Math.floor((userCount || 10) * 0.4) },
  { name: 'Support', value: Math.floor((userCount || 10) * 0.25) },
  { name: 'Both', value: Math.floor((userCount || 10) * 0.2) },
  { name: 'None', value: Math.max(1, Math.floor((userCount || 10) * 0.15)) },
];

const generateDeptData = (users) => {
  const depts = {};
  (users || []).forEach(u => {
    const d = u.department || 'Other';
    depts[d] = (depts[d] || 0) + 1;
  });
  return Object.entries(depts).map(([name, count]) => ({ name, count }));
};

const generatePerformanceData = () => {
  const sessions = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6'];
  return sessions.map(s => ({
    session: s,
    completed: Math.floor(Math.random() * 10 + 2),
    pending: Math.floor(Math.random() * 5 + 1),
  }));
};

// ─── Searchable Reporting-Manager select ───
// Simple inline searchable dropdown. Stores the selected option's `_id`.
// value '' means no manager (the "— None —" option).
const ReportingManagerSelect = ({ options, value, onChange }) => {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const ref = useRef(null);

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const selected = options.find(o => o._id === value);
  const q = query.trim().toLowerCase();
  const filtered = q
    ? options.filter(o =>
        (o.full_name || '').toLowerCase().includes(q) ||
        (o.email || '').toLowerCase().includes(q) ||
        (o.designation || '').toLowerCase().includes(q))
    : options;

  const label = selected
    ? `${selected.full_name || selected.email}${selected.designation ? ' · ' + selected.designation : ''}`
    : '— None —';

  return (
    <div className="relative" ref={ref}>
      <button type="button" onClick={() => setOpen(o => !o)}
        className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none flex items-center justify-between gap-2 text-left">
        <span className={selected ? 'truncate' : 'truncate text-[var(--text-muted)]'}>{label}</span>
        <ChevronDown size={14} className="shrink-0 text-[var(--text-muted)]" />
      </button>
      {open && (
        <div className="absolute z-50 mt-1 w-full bg-[var(--bg-card)] border border-[var(--input-border)] rounded-md shadow-lg max-h-56 overflow-auto">
          <input autoFocus value={query} onChange={e => setQuery(e.target.value)} placeholder="Search name, email, designation…"
            className="w-full px-3 py-1.5 bg-[var(--input-bg)] border-b border-[var(--input-border)] text-[12px] text-[var(--text-main)] outline-none sticky top-0" />
          <button type="button" onClick={() => { onChange(''); setOpen(false); setQuery(''); }}
            className="w-full text-left px-3 py-1.5 text-[12px] text-[var(--text-muted)] hover:bg-[var(--input-bg)]">— None —</button>
          {filtered.map(o => (
            <button key={o._id} type="button" onClick={() => { onChange(o._id); setOpen(false); setQuery(''); }}
              className="w-full text-left px-3 py-1.5 hover:bg-[var(--input-bg)]">
              <div className="text-[12px] text-[var(--text-main)] truncate">{o.full_name || o.email}</div>
              <div className="text-[10px] text-[var(--text-muted)] truncate">{o.email}{o.designation ? ' · ' + o.designation : ''}{o.role ? ' · ' + o.role : ''}</div>
            </button>
          ))}
          {filtered.length === 0 && (
            <div className="px-3 py-2 text-[12px] text-[var(--text-muted)]">No matches</div>
          )}
        </div>
      )}
    </div>
  );
};

// ─── Main Component ───
const CompanyDetails = () => {
  const { companyId } = useParams();
  const navigate = useNavigate();
  const fileInputRef = useRef(null);
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();

  const [company, setCompany] = useState(null);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('dashboard');
  const [editMode, setEditMode] = useState(false);
  const [editData, setEditData] = useState({});
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [showAddUser, setShowAddUser] = useState(false);
  const [importStatus, setImportStatus] = useState(null);
  const [statusDropdown, setStatusDropdown] = useState(false);
  const [analytics, setAnalytics] = useState(null);
  const [fetchingAnalytics, setFetchingAnalytics] = useState(false);

  const [newUser, setNewUser] = useState({
    email: '', password: '', first_name: '', last_name: '', mobile: '',
    role: 'clientuser', session_type: 'None', designation: '', department: 'Other',
    reporting_manager: '', level: ''
  });
  // Reporting-manager dropdown options (active users of THIS company)
  const [managerOptions, setManagerOptions] = useState([]);
  // SMOP dropdown options (staff & admin users)
  const [smopOptions, setSmopOptions] = useState([]);

  useEffect(() => {
    api.get('/companies/smop-options')
      .then(res => setSmopOptions(Array.isArray(res.data) ? res.data : []))
      .catch(() => setSmopOptions([]));
  }, []);

  // Training Path State
  const [trainingPath, setTrainingPath] = useState([]);
  const [fetchingPath, setFetchingPath] = useState(false);
  const [selectedSessionId, setSelectedSessionId] = useState(null);
  const [sessionTasks, setSessionTasks] = useState([]);
  const [fetchingTasks, setFetchingTasks] = useState(false);
  const [expandedBatches, setExpandedBatches] = useState({});
  const [expandedQuarters, setExpandedQuarters] = useState({});
  const [uploadingFile, setUploadingFile] = useState(false);

  const canUpdate = user?.role === 'superadmin' || user?.permissions?.companies?.update;
  const canDelete = user?.role === 'superadmin' || user?.permissions?.companies?.delete;
  const canReadUsers = user?.role === 'superadmin' || user?.permissions?.users?.read;
  const canReadAnalytics = user?.role === 'superadmin' || user?.permissions?.companies?.read;
  const isStaff = ['superadmin', 'admin'].includes(user?.role);
  // TPMS toggle is Admin / Super Admin only — deliberately stricter than the ORM
  // toggle, which also accepts a companies.update permission grant.
  const isTpmsToggler = ['superadmin', 'admin'].includes(user?.role);
  // HRMS follows the TPMS rule (Admin / Super Admin only). Mirrors the server-side check
  // in routes/company.py update_company_hrms_access.
  const isHrmsToggler = canToggleHrms(user);

  const fetchData = async () => {
    try {
      const requests = [api.get(`/companies/${companyId}`)];
      if (canReadUsers) {
        requests.push(api.get(`/companies/${companyId}/users`));
      }
      
      const responses = await Promise.all(requests);
      setCompany(responses[0].data);
      setEditData(responses[0].data);
      
      if (canReadUsers && responses[1]) {
        setUsers(responses[1].data);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const fetchAnalytics = async () => {
    if (!canReadAnalytics) return;
    setFetchingAnalytics(true);
    try {
        const res = await api.get(`/companies/${companyId}/analytics`);
        setAnalytics(res.data);
    } catch (err) {
        console.error("Failed to fetch analytics:", err);
    } finally {
        setFetchingAnalytics(false);
    }
  };

  const fetchTrainingPath = async () => {
    setFetchingPath(true);
    try {
        const res = await api.get(`/companies/${companyId}/training-path`);
        setTrainingPath(res.data);
    } catch (err) {
        console.error(err);
    } finally {
        setFetchingPath(false);
    }
  };

  const fetchSessionTasks = async (sessionId) => {
    setFetchingTasks(true);
    try {
        const res = await api.get(`/companies/${companyId}/sessions/${sessionId}/tasks`);
        setSessionTasks(res.data);
        setSelectedSessionId(sessionId);
    } catch (err) {
        console.error(err);
    } finally {
        setFetchingTasks(false);
    }
  };

  useEffect(() => { 
    fetchData(); 
    if (activeTab === 'dashboard') fetchAnalytics();
    if (activeTab === 'batches') fetchTrainingPath();
  }, [companyId, activeTab]);

  // Load reporting-manager options for THIS company when the Add-User modal opens.
  // Refetches if the company (companyId) changes.
  useEffect(() => {
    if (!showAddUser || !companyId) return;
    api.get('/users/reporting-manager-options', { params: { company_id: companyId } })
      .then(res => setManagerOptions(Array.isArray(res.data) ? res.data : []))
      .catch(() => setManagerOptions([]));
  }, [showAddUser, companyId]);

  // ─── Handlers ───
  const handleSaveEdit = async () => {
    try {
      const { _id, created_at, admin_id, is_active, status, ...fields } = editData;
      await api.put(`/companies/${companyId}`, fields);
      setEditMode(false);
      showSuccess('Company details updated successfully');
      fetchData();
    } catch (err) { showError('Update failed'); }
  };

  const handleStatusChange = async (newStatus) => {
    try {
      await api.patch(`/companies/${companyId}/status`, { status: newStatus });
      setStatusDropdown(false);
      showSuccess(`Company status changed to ${newStatus}`);
      fetchData();
    } catch (err) { showError('Status change failed'); }
  };

  const handleDelete = async () => {
    try {
      await api.delete(`/companies/${companyId}`);
      showSuccess('Company deleted successfully');
      navigate('/companies');
    } catch (err) { showError('Delete failed'); }
  };

  const handleToggleOrm = async () => {
    const next = !(company.orm_enabled ?? true);
    try {
      await api.patch(`/companies/${companyId}/orm-access`, { enabled: next });
      setCompany(prev => ({ ...prev, orm_enabled: next }));
      showSuccess(`ORM ${next ? 'enabled' : 'disabled'} for ${company.name}`);
    } catch (err) { showError('Failed to update ORM access'); }
  };

  // TPMS is opt-in per company — absent flag means OFF, unlike ORM which defaults on.
  const handleToggleTpms = async () => {
    const next = !(company.tpms_enabled ?? false);
    try {
      await api.patch(`/companies/${companyId}/tpms-access`, { enabled: next });
      setCompany(prev => ({ ...prev, tpms_enabled: next }));
      showSuccess(`TPMS ${next ? 'enabled' : 'disabled'} for ${company.name}`);
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to update TPMS access');
    }
  };

  // Task Management (Delegation) — opt-in per company; absent flag means OFF. Gates the
  // Task Management sidebar module for this company's client-side users.
  const handleToggleDelegation = async () => {
    const next = !(company.delegation_enabled ?? false);
    try {
      await api.patch(`/companies/${companyId}/delegation-access`, { enabled: next });
      setCompany(prev => ({ ...prev, delegation_enabled: next }));
      showSuccess(`Task Management ${next ? 'enabled' : 'disabled'} for ${company.name}`);
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to update Task Management access');
    }
  };

  // HRMS — opt-in per company; absent flag means OFF. Admin / Super Admin only (stricter
  // than the ORM toggle) because HRMS holds payroll and personal data.
  const handleToggleHrms = async () => {
    const next = !(company.hrms_enabled ?? false);
    try {
      await setHrmsAccess(companyId, next);
      setCompany(prev => ({ ...prev, hrms_enabled: next }));
      showSuccess(`HRMS ${next ? 'enabled' : 'disabled'} for ${company.name}`);
    } catch (err) {
      showError(err.response?.data?.detail || 'Failed to update HRMS access');
    }
  };

  const handleAddUser = async (e) => {
    e.preventDefault();
    try {
      const cleanUser = { ...newUser };
      if (!cleanUser.mobile) cleanUser.mobile = null;
      if (!cleanUser.designation) cleanUser.designation = null;
      if (!cleanUser.reporting_manager) cleanUser.reporting_manager = null;
      if (!cleanUser.level) cleanUser.level = null;
      await api.post(`/companies/${companyId}/users/bulk`, [cleanUser]);
      setShowAddUser(false);
      showSuccess('User added successfully');
      setNewUser({ email: '', password: '', first_name: '', last_name: '', mobile: '', role: 'clientuser', session_type: 'None', designation: '', department: 'Other', reporting_manager: '', level: '' });
      fetchData();
    } catch (err) { showError(err.response?.data?.detail || 'Failed to create user'); }
  };

  const handleExportTemplate = async () => {
    try {
      const response = await api.get(`/companies/${companyId}/users/template`, { responseType: 'blob' });
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `user_template_${companyId}.xlsx`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      showSuccess('Template downloaded');
    } catch (err) { showError(err.response?.data?.detail || 'Template download failed'); }
  };

  const handleImportFile = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await api.post(`/companies/${companyId}/users/import`, formData, { headers: { 'Content-Type': 'multipart/form-data' } });
      setImportStatus(res.data);
      const msg = res.data.message || `Import completed: ${res.data.created || 0} created, ${res.data.updated || 0} updated`;
      showSuccess(msg);
      fetchData();
    } catch (err) { showError(err.response?.data?.detail || 'Import failed'); }
    e.target.value = '';
  };

  const handleToggleTask = async (sessionId, taskIndex) => {
    try {
        await api.patch(`/companies/${companyId}/sessions/${sessionId}/tasks/${taskIndex}/toggle`);
        // Update local state
        setSessionTasks(prev => prev.map(t => t.index === taskIndex ? { ...t, is_done: !t.is_done } : t));
    } catch (err) {
        showError("Failed to toggle task");
    }
  };

  const handleLearnerUpload = async (e, sessionId) => {
    const file = e.target.files[0];
    if (!file) return;
    
    setUploadingFile(true);
    const formData = new FormData();
    formData.append('file', file);
    
    try {
        await api.post(`/calendar/events/${sessionId}/learner-upload`, formData, {
            headers: { 'Content-Type': 'multipart/form-data' }
        });
        showSuccess("File uploaded successfully!");
        // Refresh session data if needed or just show success
        fetchSessionTasks(sessionId);
    } catch (err) {
        showError("Upload failed");
    } finally {
        setUploadingFile(false);
    }
  };

  if (loading) return (
    <div className="flex items-center justify-center py-32">
      <div className="w-8 h-8 border-2 border-[var(--accent-indigo-border)] border-t-[var(--accent-indigo)] rounded-full animate-spin"></div>
    </div>
  );

  if (!company) return <div className="text-center py-20 text-[var(--text-muted)]">Company not found</div>;

  // Mapping logic for Charts
  const monthlyData = analytics?.monthly_trend || generateMonthlyData(users.length);
  const pieData = (analytics?.session_type_split && analytics.session_type_split.length > 0) ? analytics.session_type_split : generatePieData(users.length);
  const deptData = (analytics?.dept_distribution && analytics.dept_distribution.length > 0) ? analytics.dept_distribution : generateDeptData(users);
  const perfData = analytics?.performance_data || generatePerformanceData();
  const topPerformersData = (analytics?.top_performers && analytics.top_performers.length > 0) ? analytics.top_performers : [];
  
  const activeUsers = users.filter(u => u.is_active !== false).length;

  return (
    <div className="space-y-6">
      {/* ─── Header ─── */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-4">
          <button onClick={() => navigate('/companies')} className="p-2 rounded-lg text-[var(--text-muted)] hover:bg-[var(--accent-indigo-bg)] hover:text-[var(--accent-indigo)] transition-all">
            <ArrowLeft size={18} />
          </button>
          <div>
            <h1 className="text-xl font-bold text-[var(--text-main)] tracking-tight">{company.name}</h1>
            <p className="text-[12px] text-[var(--text-muted)]">{company.domain || 'No Domain'} · {company.company_type}</p>
          </div>
          <StatusBadge status={company.status || 'active'} />
        </div>
        <div className="flex items-center gap-2">
          {isStaff && canUpdate && (
            <ModuleToggle
              label="ORM"
              enabled={company.orm_enabled ?? true}
              onToggle={handleToggleOrm}
              title="Toggle whether this company can access the ORM module"
            />
          )}
          {/* TPMS access — a switch rather than a button, so the on/off state reads at a
              glance. Admin/Super Admin only, and off by default: a company stays dark
              until someone explicitly switches it on. */}
          {isTpmsToggler && (
            <ModuleToggle
              label="TPMS"
              enabled={company.tpms_enabled ?? false}
              onToggle={handleToggleTpms}
              title="Toggle whether this company can access the TPMS module"
            />
          )}
          {/* Task Management (Delegation) module access. Off by default: a company stays
              without the Task Management module until switched on here. */}
          {isStaff && canUpdate && (
            <ModuleToggle
              label="Task Mgmt"
              enabled={company.delegation_enabled ?? false}
              onToggle={handleToggleDelegation}
              title="Toggle whether this company can access the Task Management module"
            />
          )}
          {/* HRMS module access. Shown ONLY for the in-house company: HRMS is an
              internal recruitment and HR system, not a module the ERP's client companies
              can be given. routes/company.py refuses to enable it for anyone else, so
              rendering the switch on a client company would be offering an action the
              server answers with 403. */}
          {isHrmsToggler && isInternalCompany(company) && (
            <ModuleToggle
              label="HRMS"
              enabled={company.hrms_enabled ?? false}
              onToggle={handleToggleHrms}
              title="Toggle HRMS for the in-house company"
            />
          )}
          {canUpdate && (
            <>
              <button onClick={() => setEditMode(!editMode)} className="h-9 px-4 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-muted)] rounded-lg text-[12px] font-bold flex items-center gap-2 hover:border-[var(--accent-indigo)] hover:text-[var(--accent-indigo)] transition-all">
                <Pencil size={14} /> Edit
              </button>
              <div className="relative">
                <button onClick={() => setStatusDropdown(!statusDropdown)} className="h-9 px-4 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-muted)] rounded-lg text-[12px] font-bold flex items-center gap-2 hover:border-[var(--accent-orange)] hover:text-[var(--accent-orange)] transition-all">
                  Status <ChevronDown size={12} />
                </button>
                {statusDropdown && (
                  <div className="absolute right-0 top-11 bg-[var(--bg-card)] border border-[var(--border)] rounded-lg shadow-lg z-50 min-w-[140px] py-1">
                    {['active', 'hold', 'inactive'].map(s => (
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
            <h3 className="text-[14px] font-bold text-[var(--text-main)] mb-4">Edit Company Details</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {[
                { key: 'name', label: 'Name' }, { key: 'domain', label: 'Domain' }, { key: 'owner', label: 'Owner' },
                { key: 'email', label: 'Email' }, { key: 'contact', label: 'Contact' }, { key: 'company_type', label: 'Industry' },
                { key: 'address', label: 'Address' }, { key: 'city', label: 'City' }, { key: 'state', label: 'State' },
                { key: 'pin', label: 'PIN' }, { key: 'gst', label: 'GST' }, { key: 'members_count', label: 'Size', type: 'number' },
              ].map(f => (
                <div key={f.key} className="space-y-1">
                  <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">{f.label}</label>
                  <input type={f.type || 'text'} value={editData[f.key] || ''} onChange={e => setEditData({ ...editData, [f.key]: f.type === 'number' ? parseInt(e.target.value) : e.target.value })}
                    className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md outline-none text-[13px] font-medium text-[var(--text-main)] focus:border-[var(--accent-indigo)]" />
                </div>
              ))}
              <div className="space-y-1">
                <label className="text-[10px] font-bold text-[var(--accent-indigo)] uppercase tracking-widest flex items-center gap-1">
                  <UserCheck size={12} /> Assign SMOP
                </label>
                <select
                  value={editData.smop_id || editData.smop || (editData.smops_ids && editData.smops_ids[0]) || ''}
                  onChange={e => setEditData({ ...editData, smop_id: e.target.value, smop: e.target.value, smops_ids: e.target.value ? [e.target.value] : [] })}
                  className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--accent-indigo-border)] rounded-md outline-none text-[13px] font-bold text-[var(--text-main)] focus:border-[var(--accent-indigo)]"
                >
                  <option value="">— Unassigned —</option>
                  {smopOptions.map(opt => (
                    <option key={opt._id} value={opt._id}>
                      {opt.full_name}{opt.designation ? ` · ${opt.designation}` : ''} ({opt.role || 'Staff'})
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="flex gap-3 mt-6">
              <button onClick={handleSaveEdit} className="h-9 px-6 bg-[var(--accent-green)] text-white rounded-lg text-[12px] font-bold flex items-center gap-2"><Save size={14} /> Save Changes</button>
              <button onClick={() => { setEditMode(false); setEditData(company); }} className="h-9 px-6 bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] rounded-lg text-[12px] font-bold flex items-center gap-2"><X size={14} /> Cancel</button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ─── Tabs ─── */}
      <div className="flex gap-1 bg-[var(--bg-card)] border border-[var(--border)] p-1 rounded-xl w-fit">
        {[
          { id: 'dashboard', label: 'Company Dashboard', icon: BarChart3, show: canReadAnalytics },
          { id: 'members', label: 'Team Members', icon: Users, show: canReadUsers },
          { id: 'batches', label: 'Batches', icon: Layers, show: canReadAnalytics },
          { id: 'orm', label: 'ORM Report', icon: Target, show: canReadAnalytics },
          { id: 'orm-requests', label: 'Target Requests', icon: Inbox, show: isStaff },
        ].filter(t => t.show).map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-[12px] font-bold transition-all ${
              activeTab === tab.id
                ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'
            }`}>
            <tab.icon size={15} /> {tab.label}
          </button>
        ))}
      </div>

      {/* ─── Tab Content ─── */}
      <AnimatePresence mode="wait">
        {/* ════════════ DASHBOARD TAB ════════════ */}
        {activeTab === 'dashboard' && (
          <motion.div key="dashboard" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="space-y-6">

            {/* Company Info Row */}
            <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-6">
              <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-x-8 gap-y-1">
                <InfoRow icon={Building2} label="Company" value={company.name} />
                <InfoRow icon={Globe} label="Domain" value={company.domain} />
                <InfoRow icon={User} label="Owner" value={company.owner} />
                <InfoRow
                  icon={UserCheck}
                  label="Assigned SMOP"
                  value={(() => {
                    const smopVal = company.smop_id || company.smop || (company.smops_ids && company.smops_ids[0]);
                    if (!smopVal) return '—';
                    const opt = smopOptions.find(o => o._id === smopVal || o.email === smopVal);
                    return opt ? `${opt.full_name} (${opt.role || 'Staff'})` : smopVal;
                  })()}
                />
                <InfoRow icon={Briefcase} label="Industry" value={company.company_type} />
                <InfoRow icon={Mail} label="Email" value={company.email} />
                <InfoRow icon={Phone} label="Contact" value={company.contact} />
                <InfoRow icon={MapPin} label="Location" value={[company.city, company.state].filter(Boolean).join(', ') || '—'} />
                <InfoRow icon={Hash} label="GSTIN" value={company.gst} />
              </div>
            </div>

            {/* Stats Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <StatCard icon={Users} label="Total Members" value={users.length} sub={`${activeUsers} active`} color="indigo" />
              <StatCard icon={Layers} label="Batches" value={analytics?.total_batches ?? 0} sub="Affiliated" color="green" />
              <StatCard icon={Calendar} label="Active Sessions" value={analytics?.active_sessions ?? 0} sub="This month" color="orange" />
              <StatCard icon={Award} label="Avg. Score" value={analytics?.avg_score !== undefined ? `${analytics.avg_score}%` : '—'} sub="Global average" color="yellow" />
            </div>

            {/* Charts Row 1 */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Sessions & Attendance Line Chart */}
              <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="text-[14px] font-bold text-[var(--text-main)]">Sessions & Attendance</h3>
                    <p className="text-[11px] text-[var(--text-muted)]">Monthly session tracking</p>
                  </div>
                  <TrendingUp size={16} className="text-[var(--accent-green)]" />
                </div>
                <ResponsiveContainer width="100%" height={240}>
                  <AreaChart data={monthlyData}>
                    <defs>
                      <linearGradient id="gradIndigo" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="gradGreen" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#22c55e" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis dataKey="name" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
                    <YAxis tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
                    <Tooltip contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} />
                    <Area type="monotone" dataKey="sessions" stroke="#6366f1" fill="url(#gradIndigo)" strokeWidth={2} name="Sessions" />
                    <Area type="monotone" dataKey="attendance" stroke="#22c55e" fill="url(#gradGreen)" strokeWidth={2} name="Attendance" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>

              {/* Performance Bar Chart */}
              <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="text-[14px] font-bold text-[var(--text-main)]">Task Performance</h3>
                    <p className="text-[11px] text-[var(--text-muted)]">Completed vs pending tasks by session</p>
                  </div>
                  <Target size={16} className="text-[var(--accent-orange)]" />
                </div>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={perfData} barGap={4}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis dataKey="session" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} />
                    <YAxis tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
                    <Tooltip 
                      contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }}
                      labelStyle={{ fontWeight: 'bold', color: 'var(--text-main)', marginBottom: 4 }}
                      labelFormatter={(label, payload) => payload[0]?.payload?.full_name || label}
                    />
                    <Bar dataKey="completed" fill="#22c55e" radius={[4, 4, 0, 0]} name="Completed" />
                    <Bar dataKey="pending" fill="#f97316" radius={[4, 4, 0, 0]} name="Pending" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Charts Row 2 */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Session Type Pie */}
              <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5">
                <h3 className="text-[14px] font-bold text-[var(--text-main)] mb-1">Session Type Split</h3>
                <p className="text-[11px] text-[var(--text-muted)] mb-4">Distribution by coaching type</p>
                <ResponsiveContainer width="100%" height={200}>
                  <PieChart>
                    <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} dataKey="value" paddingAngle={4} strokeWidth={0}>
                      {pieData.map((_, i) => (
                        <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="flex flex-wrap gap-3 justify-center mt-2">
                  {pieData.map((d, i) => (
                    <div key={d.name} className="flex items-center gap-1.5">
                      <div className="w-2 h-2 rounded-full" style={{ background: CHART_COLORS[i] }}></div>
                      <span className="text-[10px] text-[var(--text-muted)] font-bold">{d.name} ({d.value})</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Department Bar */}
              <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5">
                <h3 className="text-[14px] font-bold text-[var(--text-main)] mb-1">By Department</h3>
                <p className="text-[11px] text-[var(--text-muted)] mb-4">Team distribution</p>
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={deptData} layout="vertical" barSize={16}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis type="number" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
                    <YAxis dataKey="name" type="category" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} width={80} />
                    <Tooltip contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} />
                    <Bar dataKey="count" fill="#6366f1" radius={[0, 6, 6, 0]} name="Members" />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Top Performers */}
              <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="text-[14px] font-bold text-[var(--text-main)]">Best Performers</h3>
                    <p className="text-[11px] text-[var(--text-muted)]">Top scoring members</p>
                  </div>
                  <Award size={16} className="text-[var(--accent-yellow)]" />
                </div>
                <div className="space-y-3">
                  {topPerformersData.map(p => (
                    <div key={p._id || p.email} className="flex items-center gap-3 p-2.5 rounded-lg hover:bg-[var(--input-bg)] transition-all">
                      <div className={`w-7 h-7 rounded-md flex items-center justify-center font-black text-[11px] text-white ${
                        p.rank === 1 ? 'bg-amber-500' : p.rank === 2 ? 'bg-gray-400' : 'bg-amber-700'
                      }`}>
                        {p.rank}
                      </div>
                      <div className="w-8 h-8 rounded-md flex items-center justify-center text-white font-bold text-[10px]" style={{ background: 'var(--avatar-bg)' }}>
                        {p.full_name?.charAt(0) || p.email?.charAt(0) || '?'}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-[13px] font-bold text-[var(--text-main)] truncate">{p.full_name || p.email}</p>
                        <p className="text-[10px] text-[var(--text-muted)]">{p.department || 'Training Star'}</p>
                      </div>
                      <span className="text-[14px] font-black text-[var(--accent-green)]">{p.score}%</span>
                    </div>
                  ))}
                  {topPerformersData.length === 0 && (
                    <p className="text-[12px] text-[var(--text-muted)] text-center py-8">No assessment data yet</p>
                  )}
                </div>
              </div>
            </div>

            {/* Score Trend Line */}
            <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl p-5">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="text-[14px] font-bold text-[var(--text-main)]">Average Assessment Score Trend</h3>
                  <p className="text-[11px] text-[var(--text-muted)]">Monthly average performance score</p>
                </div>
                <BookOpen size={16} className="text-[var(--accent-indigo)]" />
              </div>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={monthlyData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="name" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
                  <YAxis domain={[50, 100]} tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
                  <Tooltip contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, fontSize: 12 }} />
                  <Line type="monotone" dataKey="score" stroke="#eab308" strokeWidth={3} dot={{ fill: '#eab308', r: 4 }} name="Avg Score %" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </motion.div>
        )}

        {/* ════════════ TEAM MEMBERS TAB ════════════ */}
        {activeTab === 'members' && (
          <motion.div key="members" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
            <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl overflow-hidden">
              <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
                <div>
                  <h3 className="text-[14px] font-bold text-[var(--text-main)]">Team Members</h3>
                  <p className="text-[11px] text-[var(--text-muted)]">{users.length} users registered · {activeUsers} active</p>
                </div>
                <div className="flex items-center gap-2">
                  {canUpdate && (
                    <>
                      <input type="file" ref={fileInputRef} onChange={handleImportFile} accept=".xlsx, .xls, .csv" className="hidden" />
                      <button onClick={handleExportTemplate} className="h-8 px-3 bg-[var(--accent-green-bg)] border border-[var(--accent-green-border)] text-[var(--accent-green)] rounded-lg text-[11px] font-bold flex items-center gap-1.5 hover:opacity-80 transition-all">
                        <Download size={12} /> Template
                      </button>
                      <button onClick={() => fileInputRef.current?.click()} className="h-8 px-3 bg-[var(--accent-orange-bg)] border border-[var(--accent-orange-border)] text-[var(--accent-orange)] rounded-lg text-[11px] font-bold flex items-center gap-1.5 hover:opacity-80 transition-all">
                        <Upload size={12} /> Import
                      </button>
                      <button onClick={() => setShowAddUser(true)} className="h-8 px-3 bg-[var(--btn-primary)] text-white rounded-lg text-[11px] font-bold flex items-center gap-1.5 hover:bg-[var(--btn-primary-hover)] transition-all">
                        <Plus size={12} /> Add User
                      </button>
                    </>
                  )}
                </div>
              </div>

              {importStatus && (
                <div className="px-5 py-3 bg-[var(--accent-green-bg)] border-b border-[var(--accent-green-border)] flex items-center justify-between">
                  <span className="text-[12px] font-bold text-[var(--accent-green)]">
                    <FileSpreadsheet size={14} className="inline mr-2" />
                    Import: {importStatus.created || 0} created, {importStatus.updated || 0} updated, {importStatus.skipped || 0} skipped
                  </span>
                  <button onClick={() => setImportStatus(null)} className="text-[var(--text-muted)] hover:text-[var(--accent-red)]"><X size={14} /></button>
                </div>
              )}

              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                      <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Name</th>
                      <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Email</th>
                      <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Level</th>
                      <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Reporting Manager</th>
                      <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Role</th>
                      <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Department</th>
                      <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Session</th>
                      <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Status</th>
                      <th className="px-5 py-3 text-right text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border)]">
                    {users.map(u => {
                      const mgr = users.find(m => m._id === u.reporting_manager || m.email === u.reporting_manager);
                      const mgrDisplay = u.reporting_manager ? (mgr ? (mgr.full_name || mgr.email) : u.reporting_manager) : '—';
                      return (
                        <tr key={u._id} className="hover:bg-[var(--table-hover)] transition-all">
                          <td className="px-5 py-2.5">
                            <div className="flex items-center gap-3">
                              <div className="w-7 h-7 rounded-md flex items-center justify-center text-white font-bold text-[10px]" style={{ background: 'var(--avatar-bg)' }}>
                                {u.full_name?.charAt(0) || u.email?.charAt(0) || '?'}
                              </div>
                              <div className="flex flex-col">
                                <span className="text-[13px] font-bold text-[var(--text-main)]">{u.full_name || '—'}</span>
                                <span className="text-[10px] text-[var(--text-muted)]">{u.mobile || ''}</span>
                              </div>
                            </div>
                          </td>
                          <td className="px-5 py-2.5 text-[12px] text-[var(--text-muted)]">{u.email}</td>
                          <td className="px-5 py-2.5">
                            <span className="px-2 py-0.5 bg-indigo-50 text-[var(--accent-indigo)] border border-indigo-100 rounded-md text-[10px] font-bold uppercase">{u.level || '—'}</span>
                          </td>
                          <td className="px-5 py-2.5 text-[12px] text-[var(--text-muted)] font-medium">{mgrDisplay}</td>
                          <td className="px-5 py-2.5">
                            <span className="px-2 py-0.5 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] border border-[var(--accent-indigo-border)] rounded-md text-[10px] font-bold uppercase">{u.role}</span>
                          </td>
                          <td className="px-5 py-2.5 text-[12px] text-[var(--text-muted)] font-medium">{u.department || '—'}</td>
                          <td className="px-5 py-2.5 text-[12px] text-[var(--accent-orange)] font-bold">{u.session_type || '—'}</td>
                          <td className="px-5 py-2.5">
                            <span className={`px-2 py-0.5 rounded-md text-[10px] font-bold ${u.is_active !== false ? 'bg-[var(--status-active-bg)] text-[var(--status-active-text)]' : 'bg-[var(--accent-red-bg)] text-[var(--accent-red)]'}`}>
                              {u.is_active !== false ? 'Active' : 'Inactive'}
                            </span>
                          </td>
                          <td className="px-5 py-2.5 text-right">
                            <button onClick={() => navigate(`/members/${u._id}`)} className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] rounded-md transition-all" title="View Member Dashboard">
                              <ExternalLink size={14} />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                    {users.length === 0 && (
                      <tr><td colSpan={9} className="px-5 py-12 text-center text-[var(--text-muted)] text-[13px]">No users yet. Add users or import via template.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </motion.div>
        )}

        {/* ════════════ BATCHES & TRAINING TAB ════════════ */}
        {activeTab === 'batches' && (
          <motion.div key="batches" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
            
            {/* Left Column: Hierarchical List */}
            <div className="lg:col-span-4 space-y-4">
              <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl overflow-hidden shadow-sm">
                <div className="p-4 border-b border-[var(--border)] bg-[var(--input-bg)]">
                  <h3 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-[0.15em] flex items-center gap-2">
                    <Layers size={14} className="text-[var(--accent-indigo)]" /> Assigned Training Path
                  </h3>
                </div>
                
                <div className="p-2 space-y-1 max-h-[70vh] overflow-y-auto custom-scrollbar">
                  {fetchingPath ? (
                    <div className="py-10 flex flex-col items-center gap-2 opacity-40">
                      <div className="w-5 h-5 border-2 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"></div>
                      <span className="text-[10px] font-bold uppercase tracking-widest">Loading Path...</span>
                    </div>
                  ) : trainingPath.length > 0 ? trainingPath.map(batch => (
                    <div key={batch.id} className="space-y-1">
                      {/* Batch Level */}
                      <button 
                        onClick={() => setExpandedBatches(prev => ({ ...prev, [batch.id]: !prev[batch.id] }))}
                        className={`w-full flex items-center gap-3 p-3 rounded-xl transition-all ${expandedBatches[batch.id] ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]' : 'hover:bg-[var(--input-bg)] text-[var(--text-muted)]'}`}
                      >
                        <Layers size={16} />
                        <span className="text-[12px] font-black uppercase tracking-tight flex-1 text-left truncate">{batch.name}</span>
                        <ChevronRight size={14} className={`transition-transform ${expandedBatches[batch.id] ? 'rotate-90' : ''}`} />
                      </button>

                      {/* Quarters Level */}
                      <AnimatePresence>
                        {expandedBatches[batch.id] && (
                          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="pl-4 overflow-hidden space-y-1">
                            {batch.quarters?.map(quarter => (
                              <div key={quarter.id} className="space-y-1">
                                <button 
                                  onClick={() => setExpandedQuarters(prev => ({ ...prev, [quarter.id]: !prev[quarter.id] }))}
                                  className={`w-full flex items-center gap-3 p-2.5 rounded-lg transition-all ${expandedQuarters[quarter.id] ? 'text-[var(--accent-orange)]' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}
                                >
                                  <div className="w-1 h-4 rounded-full bg-[var(--border)]"></div>
                                  <span className="text-[11px] font-bold uppercase flex-1 text-left truncate">{quarter.name}</span>
                                  <ChevronRight size={12} className={`transition-transform ${expandedQuarters[quarter.id] ? 'rotate-90' : ''}`} />
                                </button>

                                {/* Sessions Level */}
                                <AnimatePresence>
                                  {expandedQuarters[quarter.id] && (
                                    <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="pl-6 overflow-hidden space-y-1">
                                      {quarter.sessions?.map(session => (
                                        <button 
                                          key={session.id}
                                          onClick={() => fetchSessionTasks(session.id)}
                                          className={`w-full flex items-center gap-2.5 p-2 rounded-lg transition-all text-left ${selectedSessionId === session.id ? 'bg-white shadow-sm border border-[var(--border)] text-[var(--accent-green)]' : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]'}`}
                                        >
                                          <div className={`w-1.5 h-1.5 rounded-full ${selectedSessionId === session.id ? 'bg-[var(--accent-green)] scale-125' : 'bg-[var(--border)]'}`}></div>
                                          <div className="flex-1 min-w-0">
                                            <p className="text-[11px] font-bold truncate leading-tight">{session.title}</p>
                                            <p className="text-[9px] opacity-60 tracking-wider">
                                              {new Date(session.start).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
                                            </p>
                                          </div>
                                          {session.status === 'completed' && <CheckCircle size={12} className="text-[var(--accent-green)]" />}
                                        </button>
                                      ))}
                                    </motion.div>
                                  )}
                                </AnimatePresence>
                              </div>
                            ))}
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                  )) : (
                    <div className="py-12 text-center opacity-40">
                      <Layers size={32} className="mx-auto mb-2" />
                      <p className="text-[10px] font-black uppercase tracking-widest">No assigned batches</p>
                    </div>
                  )}
                </div>
              </div>

              <div className="bg-amber-50 border border-amber-100 rounded-2xl p-4 flex gap-3">
                <AlertTriangle size={16} className="text-amber-500 shrink-0 mt-0.5" />
                <p className="text-[10px] text-amber-700 font-bold leading-relaxed uppercase tracking-tight">
                  Session locks are managed by staff. Once a session is marked "Completed", associated AI Engine access is unlocked for learners.
                </p>
              </div>
            </div>

            {/* Right Column: Session Details & Actions */}
            <div className="lg:col-span-8">
              {fetchingTasks ? (
                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-20 flex flex-col items-center justify-center gap-4 text-center">
                  <div className="w-10 h-10 border-4 border-[var(--accent-indigo)] border-t-transparent rounded-full animate-spin"></div>
                  <p className="text-[11px] font-black text-[var(--accent-indigo)] uppercase tracking-widest">Synchronizing Neural Path...</p>
                </div>
              ) : selectedSessionId ? (
                <div className="space-y-6">
                  {/* Session Header Card */}
                  <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-8 shadow-sm relative overflow-hidden group">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-[var(--accent-indigo)] opacity-[0.03] rounded-full -mr-16 -mt-16 group-hover:scale-150 transition-transform duration-1000"></div>
                    <div className="relative z-10">
                      <div className="flex items-center gap-3 mb-4">
                        <div className="px-3 py-1 bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] rounded-lg text-[10px] font-black uppercase tracking-widest border border-[var(--accent-indigo-border)]">Session Logic</div>
                        <div className={`px-3 py-1 rounded-lg text-[10px] font-black uppercase tracking-widest border ${trainingPath.flatMap(b => b.quarters).flatMap(q => q.sessions).find(s => s.id === selectedSessionId)?.status === 'completed' ? 'bg-emerald-50 text-emerald-600 border-emerald-100' : 'bg-amber-50 text-amber-600 border-amber-100'}`}>
                          {trainingPath.flatMap(b => b.quarters).flatMap(q => q.sessions).find(s => s.id === selectedSessionId)?.status}
                        </div>
                      </div>
                      <h2 className="text-2xl font-black text-[var(--text-main)] italic uppercase tracking-tight leading-none mb-2">
                        {trainingPath.flatMap(b => b.quarters).flatMap(q => q.sessions).find(s => s.id === selectedSessionId)?.title}
                      </h2>
                      <div className="flex items-center gap-6 text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-widest">
                        <span className="flex items-center gap-2"><Calendar size={14} /> {new Date(trainingPath.flatMap(b => b.quarters).flatMap(q => q.sessions).find(s => s.id === selectedSessionId)?.start).toLocaleDateString('en-IN', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' })}</span>
                        <span className="flex items-center gap-2"><Target size={14} /> Quarter Training Task</span>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {/* Task Progress Section */}
                    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] overflow-hidden flex flex-col">
                      <div className="p-6 border-b border-[var(--border)] flex items-center justify-between">
                        <h4 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest flex items-center gap-2">
                          <CheckCircle2 size={16} className="text-[var(--accent-green)]" /> Company Tasks
                        </h4>
                        <div className="text-[11px] font-black text-[var(--accent-green)] bg-[var(--accent-green-bg)] px-2.5 py-0.5 rounded-lg border border-[var(--accent-green-border)]">
                          {sessionTasks.filter(t => t.is_done).length}/{sessionTasks.length} Done
                        </div>
                      </div>
                      <div className="p-4 flex-1 space-y-2 overflow-y-auto no-scrollbar max-h-[350px]">
                        {sessionTasks.length > 0 ? sessionTasks.map(task => (
                          <div 
                            key={task.index}
                            onClick={() => handleToggleTask(selectedSessionId, task.index)}
                            className={`flex items-start gap-4 p-4 rounded-2xl border transition-all cursor-pointer group ${task.is_done ? 'bg-[var(--accent-green-bg)] border-[var(--accent-green-border)]' : 'bg-[var(--input-bg)] border-transparent hover:border-[var(--accent-indigo)]'}`}
                          >
                            <div className={`mt-0.5 w-5 h-5 rounded-md flex items-center justify-center transition-all ${task.is_done ? 'bg-[var(--accent-green)] text-white' : 'bg-white border-2 border-[var(--border)] group-hover:border-[var(--accent-indigo)]'}`}>
                              {task.is_done ? <CheckCircle size={14} /> : <Circle size={14} className="opacity-0 group-hover:opacity-20" />}
                            </div>
                            <div className="flex-1 min-w-0">
                              <p className={`text-[13px] font-black uppercase tracking-tight transition-all ${task.is_done ? 'text-[var(--accent-green)] line-through' : 'text-[var(--text-main)]'}`}>
                                {task.label || task.title || 'In-Session Milestone'}
                              </p>
                              {task.is_done && task.completed_by && (
                                <div className="flex items-center gap-2 mt-1 px-2 py-0.5 bg-emerald-50 border border-emerald-100 rounded-md w-fit">
                                  <User size={10} className="text-emerald-600" />
                                  <span className="text-[9px] font-black text-emerald-700 uppercase tracking-tighter">
                                    Done by: {task.completed_by} {task.completed_at ? `· ${new Date(task.completed_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}` : ''}
                                  </span>
                                </div>
                              )}
                              {task.description && (
                                <p className={`text-[10px] font-bold mt-1 leading-relaxed ${task.is_done ? 'opacity-40' : 'text-[var(--text-muted)]'}`}>
                                  {task.description}
                                </p>
                              )}
                            </div>
                          </div>
                        )) : (
                          <div className="py-12 flex flex-col items-center justify-center opacity-30 italic">
                            <Bot size={32} className="mb-2" />
                            <p className="text-[10px] font-black uppercase tracking-widest">No predefined tasks for this session</p>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Content Upload Section */}
                    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] overflow-hidden flex flex-col">
                      <div className="p-6 border-b border-[var(--border)] flex items-center justify-between">
                        <h4 className="text-[12px] font-black text-[var(--text-main)] uppercase tracking-widest flex items-center gap-2">
                          <UploadCloud size={16} className="text-[var(--accent-indigo)]" /> Learner Contents
                        </h4>
                        <label className={`h-8 px-4 rounded-xl flex items-center gap-1.5 text-[10px] font-black uppercase tracking-widest cursor-pointer transition-all ${uploadingFile ? 'bg-gray-100 text-gray-400' : 'bg-[var(--accent-indigo)] text-white hover:opacity-90 shadow-lg shadow-indigo-100'}`}>
                          {uploadingFile ? 'Uploading...' : <><Plus size={12} /> Upload Content</>}
                          <input type="file" className="hidden" disabled={uploadingFile} onChange={(e) => handleLearnerUpload(e, selectedSessionId)} />
                        </label>
                      </div>
                      
                      <div className="p-4 flex-1 space-y-2 overflow-y-auto no-scrollbar max-h-[350px]">
                        {(trainingPath.flatMap(b => b.quarters).flatMap(q => q.sessions).find(s => s.id === selectedSessionId)?.learner_contents || []).length > 0 ? (
                           trainingPath.flatMap(b => b.quarters).flatMap(q => q.sessions).find(s => s.id === selectedSessionId)?.learner_contents.map(content => (
                            <a 
                              href={content.url} 
                              target="_blank" 
                              rel="noopener noreferrer"
                              key={content.id}
                              className="flex items-center gap-4 p-4 bg-[var(--input-bg)] border border-transparent rounded-2xl hover:border-[var(--accent-indigo)] hover:bg-white transition-all group"
                            >
                              <div className="w-10 h-10 rounded-xl bg-white border border-[var(--border)] flex items-center justify-center text-[var(--accent-indigo)] group-hover:scale-110 transition-transform">
                                <FileText size={20} />
                              </div>
                              <div className="flex-1 min-w-0">
                                <p className="text-[12px] font-black text-[var(--text-main)] uppercase truncate tracking-tight">{content.name}</p>
                                <p className="text-[9px] text-[var(--text-muted)] font-bold mt-0.5">
                                  {content.uploader_name} · {new Date(content.uploaded_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                                </p>
                              </div>
                              <Download size={14} className="text-[var(--text-muted)] group-hover:text-[var(--accent-indigo)]" />
                            </a>
                           ))
                        ) : (
                          <div className="py-12 flex flex-col items-center justify-center opacity-30 italic">
                            <UploadCloud size={32} className="mb-2" />
                            <p className="text-[10px] font-black uppercase tracking-widest">No contents uploaded by learners yet</p>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Quick Resources (Optional) */}
                  <div className="bg-indigo-50 border border-indigo-100 rounded-3xl p-6">
                    <h5 className="text-[11px] font-black text-[var(--accent-indigo)] uppercase tracking-[0.2em] mb-4 flex items-center gap-2">
                       <BookOpen size={14} /> Training Resources & Materials
                    </h5>
                    <div className="flex flex-wrap gap-2">
                      {(trainingPath.flatMap(b => b.quarters).flatMap(q => q.sessions).find(s => s.id === selectedSessionId)?.resources || []).length > 0 ? (
                         trainingPath.flatMap(b => b.quarters).flatMap(q => q.sessions).find(s => s.id === selectedSessionId)?.resources.map(r => (
                           <a key={r.id} href={r.url} target="_blank" rel="noopener noreferrer" className="px-4 py-2 bg-white border border-indigo-100 rounded-xl text-[11px] font-black text-indigo-700 uppercase tracking-tighter hover:border-[var(--accent-indigo)] transition-all flex items-center gap-2">
                             <ExternalLink size={12} /> {r.name}
                           </a>
                         ))
                      ) : (
                        <p className="text-[10px] text-indigo-400 font-bold uppercase tracking-widest italic">No shared materials for this session</p>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] p-24 text-center">
                  <div className="w-20 h-20 bg-[var(--input-bg)] border border-[var(--border)] rounded-[32px] mx-auto flex items-center justify-center mb-6 text-[var(--text-muted)] opacity-50">
                    <Zap size={32} />
                  </div>
                  <h3 className="text-xl font-black text-[var(--text-main)] uppercase italic tracking-tight mb-2">Select a Neural Node</h3>
                  <p className="text-[11px] text-[var(--text-muted)] font-bold uppercase tracking-widest max-w-xs mx-auto opacity-60">Choose a session to view detailed tasks and manage corporate training progress.</p>
                </div>
              )}
            </div>
          </motion.div>
        )}

        {/* ════════════ ORM REPORT TAB ════════════ */}
        {activeTab === 'orm' && (
          <ORMReportTab key="orm" companyId={companyId} companyName={company.name} />
        )}

        {/* ════════════ ORM TARGET REQUESTS TAB ════════════ */}
        {activeTab === 'orm-requests' && isStaff && (
          <ORMTargetRequestsTab key="orm-requests" companyId={companyId} />
        )}
      </AnimatePresence>

      {/* ─── Delete Confirm Modal ─── */}
      <Modal isOpen={showDeleteConfirm} onClose={() => setShowDeleteConfirm(false)} title="Confirm Deletion">
        <div className="space-y-4 text-center py-4">
          <div className="w-16 h-16 bg-[var(--accent-red-bg)] rounded-xl mx-auto flex items-center justify-center">
            <AlertTriangle size={32} className="text-[var(--accent-red)]" />
          </div>
          <p className="text-[14px] font-bold text-[var(--text-main)]">Delete "{company.name}"?</p>
          <p className="text-[12px] text-[var(--text-muted)]">This will permanently remove the company and all {users.length} users. Cannot be undone.</p>
          <div className="flex gap-3 justify-center pt-2">
            <button onClick={() => setShowDeleteConfirm(false)} className="px-6 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[13px] font-bold text-[var(--text-muted)]">Cancel</button>
            <button onClick={handleDelete} className="px-6 py-2 bg-[var(--accent-red)] text-white rounded-lg text-[13px] font-bold hover:opacity-90 transition-all">Delete Permanently</button>
          </div>
        </div>
      </Modal>

      {/* ─── Add User Modal ─── */}
      <Modal isOpen={showAddUser} onClose={() => setShowAddUser(false)} title="Add New User">
        <form onSubmit={handleAddUser} className="space-y-4 px-1">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1"><label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">First Name</label><input className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none" value={newUser.first_name} onChange={e => setNewUser({...newUser, first_name: e.target.value})} /></div>
            <div className="space-y-1"><label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Last Name</label><input className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none" value={newUser.last_name} onChange={e => setNewUser({...newUser, last_name: e.target.value})} /></div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1"><label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Email *</label><input type="email" required className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none" value={newUser.email} onChange={e => setNewUser({...newUser, email: e.target.value})} /></div>
            <div className="space-y-1"><label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Password *</label><input type="password" required className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none" value={newUser.password} onChange={e => setNewUser({...newUser, password: e.target.value})} /></div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1"><label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Mobile</label><input className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none" value={newUser.mobile} onChange={e => setNewUser({...newUser, mobile: e.target.value})} /></div>
            <div className="space-y-1"><label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Designation</label><input className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none" value={newUser.designation} onChange={e => setNewUser({...newUser, designation: e.target.value})} /></div>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-1"><label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Role</label>
              <select className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none" value={newUser.role} onChange={e => setNewUser({...newUser, role: e.target.value})}>
                <option value="clientadmin">ClientAdmin</option><option value="clientuser">ClientUser</option>
              </select></div>
            <div className="space-y-1"><label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Session Type</label>
              <select className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none" value={newUser.session_type} onChange={e => setNewUser({...newUser, session_type: e.target.value})}>
                <option value="Core">Core</option><option value="Support">Support</option><option value="Both">Both</option><option value="None">None</option>
              </select></div>
            <div className="space-y-1"><label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Department</label>
              <select className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none" value={newUser.department} onChange={e => setNewUser({...newUser, department: e.target.value})}>
                <option value="HOD">HOD</option><option value="Manager">Manager</option><option value="Implementor">Implementor</option><option value="EA">EA</option><option value="MD">MD</option><option value="HR">HR</option><option value="Other">Other</option>
              </select></div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1"><label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Reporting Manager</label>
              <ReportingManagerSelect options={managerOptions} value={newUser.reporting_manager} onChange={val => setNewUser({...newUser, reporting_manager: val})} />
            </div>
            <div className="space-y-1"><label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Level</label>
              <input className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md text-[13px] text-[var(--text-main)] outline-none" placeholder="e.g. L1, L2, Manager" value={newUser.level} onChange={e => setNewUser({...newUser, level: e.target.value})} />
            </div>
          </div>
          <div className="flex gap-3 mt-6">
            <button type="submit" className="flex-1 py-2 bg-[var(--btn-primary)] text-white rounded-lg text-[13px] font-bold hover:bg-[var(--btn-primary-hover)] transition-all">Create User</button>
          </div>
        </form>
      </Modal>
    </div>
  );
};

export default CompanyDetails;
