import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import Button from '../components/common/Button';
import Modal from '../components/common/Modal';
import { useNotification } from '../context/NotificationContext';
import {  AnimatePresence , motion } from 'framer-motion';
import { 
  Plus, Building2, Globe, Users, Mail, User, 
  MapPin, Hash, Briefcase, Phone,
  ChevronRight, ChevronLeft, CheckCircle2, Lock,
  LayoutGrid, List, Search, Filter, MoreVertical,
  ExternalLink, Activity
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { setHrmsAccess } from '../services/hrmsApi';

const IconicInput = ({ icon: Icon, label, ...props }) => (
  <div className="space-y-1 group">
    <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest ml-0.5">
      {label}
    </label>
    <div className="relative flex items-center">
      <div className="absolute left-3 text-[var(--text-muted)]">
        <Icon size={14} />
      </div>
      <input 
        {...props}
        className="w-full pl-9 pr-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md outline-none focus:ring-4 focus:border-[var(--accent-indigo)] text-[13px] font-medium text-[var(--text-main)] transition-all"
        style={{ '--tw-ring-color': 'var(--input-focus-ring)' }}
      />
    </div>
  </div>
);

const CompanyManagement = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();
  const [companies, setCompanies] = useState([]);
  // Which row is mid-save. Tracked by id rather than a bare boolean so toggling one
  // company does not grey out every other button in the table.
  const [hrmsBusy, setHrmsBusy] = useState(null);

  /**
   * Switch Client Hiring on or off for a client company.
   *
   * The flag means different things on different companies: on Sparsh Magic's own tenant
   * it opens the whole HRMS module, on a client company it opens Client Hiring and
   * nothing else. This list only ever shows client companies, so here it is the latter.
   *
   * Updated in place on success rather than by refetching the list: the server is the
   * one that decides, and it has just told us what it decided.
   */
  const toggleClientHiring = async (company) => {
    const next = !(company.hrms_enabled ?? false);
    setHrmsBusy(company._id);
    try {
      await setHrmsAccess(company._id, next);
      setCompanies((rows) => rows.map((r) =>
        (r._id === company._id ? { ...r, hrms_enabled: next } : r)));
    } catch (err) {
      alert(err?.response?.data?.detail
        || 'Client Hiring access could not be changed.');
    } finally {
      setHrmsBusy(null);
    }
  };
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [viewMode, setViewMode] = useState('table');
  const [searchTerm, setSearchTerm] = useState('');
  const [step, setStep] = useState(1);
  
  const [formData, setFormData] = useState({
    company: {
      name: '', domain: '', owner: '', email: '', contact: '',
      address: '', city: '', state: '', country: 'India', pin: '',
      gst: '', company_type: 'Manufacturing', members_count: 0
    },
    admin: {
      first_name: '', last_name: '', email: '', mobile: '',
      password: '', session_type: 'Both', designation: '', department: 'MD'
    }
  });

  const canCreate = user?.role === 'superadmin' || user?.permissions?.companies?.create;

  const fetchCompanies = async () => {
    try {
      const response = await api.get('/companies');
      setCompanies(response.data);
    } catch (error) {
      console.error('Error fetching companies:', error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => { fetchCompanies(); }, []);

  const filteredCompanies = companies.filter(c => 
    c.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    c.domain?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    c.city?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleOnboard = async (e) => {
    e.preventDefault();
    
    // 1. Validation for Step 1
    if (!formData.company.name) {
      showError("Please provide the Company Name (Step 1).");
      setStep(1);
      return;
    }

    // 2. Navigation / Submission Logic
    if (step < 3) {
      // If Enter is pressed on Step 1 or 2, just go to next step
      nextStep();
      return;
    }

    // 3. Validation for Step 3 (Final Submission)
    if (!formData.admin.email || !formData.admin.password) {
      showError("Admin Email and Password are required to complete onboarding.");
      return;
    }

    try {
      // 1. Prepare Company Data
      const cleanCompany = { ...formData.company };
      // Convert empty strings to null for text fields
      ['domain', 'owner', 'email', 'contact', 'address', 'city', 'state', 'pin', 'gst'].forEach(key => {
        if (!cleanCompany[key]) cleanCompany[key] = null;
      });
      // Safety check for numeric fields
      cleanCompany.members_count = parseInt(cleanCompany.members_count) || 0;

      // 2. Prepare Admin Data
      const cleanAdmin = { ...formData.admin };
      // Note: Only convert fields that are truly optional in the backend to null
      ['first_name', 'last_name', 'mobile', 'designation'].forEach(key => {
        if (!cleanAdmin[key]) cleanAdmin[key] = (cleanAdmin[key] === "" ? null : cleanAdmin[key]);
      });

      await api.post('/companies', { company: cleanCompany, admin: cleanAdmin });
      setIsModalOpen(false);
      showSuccess(`Company "${formData.company.name}" successfully onboarded!`);
      resetForm();
      fetchCompanies();
    } catch (error) {
      console.error('Error onboarding:', error);
      const detail = error.response?.data?.detail;
      let message = 'Onboarding failed. Please check all fields.';
      if (Array.isArray(detail)) {
        message = `Validation Error: ${detail.map(d => `${d.loc.join('.')} - ${d.msg}`).join(', ')}`;
      } else if (typeof detail === 'string') {
        message = detail;
      }
      showError(message);
    }
  };

  const resetForm = () => {
    setFormData({
      company: { name: '', domain: '', owner: '', email: '', contact: '', address: '', city: '', state: '', country: 'India', pin: '', gst: '', company_type: 'Manufacturing', members_count: 0 },
      admin: { first_name: '', last_name: '', email: '', mobile: '', password: '', session_type: 'Both', designation: '', department: 'MD' }
    });
    setStep(1);
  };

  const nextStep = () => setStep(s => s + 1);
  const prevStep = () => setStep(s => s - 1);

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-[var(--text-main)] tracking-tight">Companies</h1>
          <p className="text-[13px] text-[var(--text-muted)] font-medium">Manage your client organizations and their admins.</p>
        </div>
        
        <div className="flex items-center gap-3">
          <div className="flex bg-[var(--bg-card)] border border-[var(--border)] p-0.5 rounded-lg shadow-sm">
            <button 
              onClick={() => setViewMode('card')}
              className={`p-1.5 rounded-md transition-all ${viewMode === 'card' ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]' : 'text-[var(--text-muted)]'}`}
            >
              <LayoutGrid size={16} />
            </button>
            <button 
              onClick={() => setViewMode('table')}
              className={`p-1.5 rounded-md transition-all ${viewMode === 'table' ? 'bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]' : 'text-[var(--text-muted)]'}`}
            >
              <List size={16} />
            </button>
          </div>

          {canCreate && (
            <button 
              onClick={() => setIsModalOpen(true)} 
              className="h-10 px-4 bg-[var(--btn-primary)] hover:bg-[var(--btn-primary-hover)] text-white font-bold text-[13px] rounded-lg flex items-center gap-2 transition-all shadow-sm"
            >
              <Plus size={16} />
              Add Company
            </button>
          )}
        </div>
      </div>

      {/* Filter Bar */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] p-3 rounded-xl flex items-center gap-4 shadow-sm">
        <div className="flex-1 relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input 
            type="text" 
            placeholder="Search companies..." 
            className="w-full pl-9 pr-4 h-9 bg-[var(--input-bg)] border border-transparent rounded-lg outline-none focus:border-[var(--accent-indigo)] text-[13px] font-medium text-[var(--text-main)] transition-all placeholder:text-[var(--text-muted)]"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        <button className="flex items-center gap-1.5 h-9 px-4 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-muted)] font-bold text-[11px] uppercase tracking-wider rounded-lg hover:border-[var(--accent-indigo)] hover:text-[var(--accent-indigo)] transition-all">
          <Filter size={14} /> Filter
        </button>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="py-20 flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-2 border-[var(--accent-indigo-border)] border-t-[var(--accent-indigo)] rounded-full animate-spin"></div>
          <span className="text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Loading Records...</span>
        </div>
      ) : viewMode === 'card' ? (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {filteredCompanies.map((c) => (
            <div key={c._id} className="bg-[var(--bg-card)] border border-[var(--border)] p-4 rounded-xl hover:border-[var(--accent-indigo-border)] transition-all group flex flex-col justify-between">
              <div>
                <div className="flex items-start justify-between mb-3">
                  <div className="w-10 h-10 bg-[var(--accent-indigo-bg)] rounded-lg flex items-center justify-center text-[var(--accent-indigo)]">
                    <Building2 size={20} />
                  </div>
                  <span className="text-[10px] font-bold text-[var(--badge-type-text)] uppercase tracking-widest bg-[var(--badge-type-bg)] px-2 py-1 rounded-md">
                    {c.company_type}
                  </span>
                </div>
                <h3 className="text-[14px] font-bold text-[var(--text-main)] group-hover:text-[var(--accent-indigo)] transition-colors mb-1 truncate">{c.name}</h3>
                <p className="text-[11px] text-[var(--text-muted)] font-medium mb-4 truncate">{c.domain || 'No Domain'}</p>
                
                <div className="space-y-2.5">
                  <div className="flex items-center gap-2.5">
                    <Users size={12} className="text-[var(--accent-green)]" />
                    <span className="text-[11px] font-medium text-[var(--text-muted)]">{c.members_count} Users</span>
                  </div>
                  <div className="flex items-center gap-2.5">
                    <MapPin size={12} className="text-[var(--accent-orange)]" />
                    <span className="text-[11px] font-medium text-[var(--text-muted)] truncate">{c.city}, {c.state}</span>
                  </div>
                </div>
              </div>
              
              <button onClick={() => navigate(`/companies/${c._id}`)} className="mt-5 w-full py-2 bg-[var(--input-bg)] hover:bg-[var(--accent-indigo)] hover:text-white border border-[var(--border)] hover:border-transparent rounded-lg text-[11px] font-bold text-[var(--text-muted)] transition-all flex items-center justify-center gap-2">
                View Details <ExternalLink size={12} />
              </button>
            </div>
          ))}
        </motion.div>
      ) : (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                  <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Company</th>
                  <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Type</th>
                  <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Scale</th>
                  <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Location</th>
                  <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Status</th>
                  {/* Client Hiring is the one HRMS surface a client company may reach.
                      Switching it on admits their people to the PRO-fit track and to
                      nothing else -- not payroll, employees, exits, or Sparsh Magic's
                      own internal hiring. */}
                  <th className="px-5 py-3 text-left text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Client Hiring</th>
                  <th className="px-5 py-3 text-right text-[11px] font-bold text-[var(--text-muted)] uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {filteredCompanies.map((c) => (
                  <tr key={c._id} className="hover:bg-[var(--table-hover)] transition-all">
                    <td className="px-5 py-2.5">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 bg-[var(--accent-indigo-bg)] rounded-md flex items-center justify-center font-black text-[var(--accent-indigo)] text-xs">
                          {c.name.charAt(0)}
                        </div>
                        <div className="flex flex-col">
                          <span className="text-[13px] font-bold text-[var(--text-main)]">{c.name}</span>
                          <span className="text-[10px] text-[var(--text-muted)] font-medium">{c.domain}</span>
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-2.5">
                      <span className="text-[12px] text-[var(--badge-type-text)] font-medium bg-[var(--badge-type-bg)] px-2 py-0.5 rounded-md">{c.company_type}</span>
                    </td>
                    <td className="px-5 py-2.5">
                      <span className="text-[12px] font-bold text-[var(--accent-orange)]">{c.members_count}</span>
                    </td>
                    <td className="px-5 py-2.5 text-[12px] text-[var(--text-muted)] font-medium">{c.city}</td>
                    <td className="px-5 py-2.5">
                      <span className="px-2 py-0.5 bg-[var(--status-active-bg)] text-[var(--status-active-text)] border border-[var(--status-active-border)] rounded-md text-[10px] font-bold inline-flex items-center gap-1.5">
                        <div className="w-1 h-1 bg-[var(--status-active-text)] rounded-full"></div> Active
                      </span>
                    </td>
                    <td className="px-5 py-2.5">
                      <button
                        type="button"
                        disabled={hrmsBusy === c._id}
                        onClick={() => toggleClientHiring(c)}
                        title={c.hrms_enabled
                          ? 'Switch Client Hiring off for this company'
                          : 'Let this company raise requirements and give their approvals'}
                        className={`px-2.5 py-1 rounded-md text-[11px] font-bold
                          transition-colors disabled:opacity-50 ${
                          c.hrms_enabled
                            ? 'bg-[var(--accent-green-bg,var(--input-bg))] text-[var(--accent-green,var(--text-main))]'
                            : 'bg-[var(--input-bg)] text-[var(--text-muted)]'}`}
                      >
                        {hrmsBusy === c._id
                          ? 'Saving…'
                          : (c.hrms_enabled ? 'On' : 'Off')}
                      </button>
                    </td>
                    <td className="px-5 py-2.5 text-right">
                      <button onClick={() => navigate(`/companies/${c._id}`)} className="p-1.5 text-[var(--text-muted)] hover:text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo-bg)] rounded-md transition-all" title="View Details">
                        <ExternalLink size={16} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </motion.div>
      )}

      {/* ─────────────── Onboarding Modal ─────────────── */}
      <Modal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} title="Company Onboarding" maxWidth="lg">
        <div className="px-2">
          <div className="flex items-center justify-between mb-8 px-4">
            {[1, 2, 3].map((s) => (
              <div key={s} className="flex items-center gap-2">
                <div className={`w-7 h-7 rounded-md flex items-center justify-center text-[11px] font-bold transition-all ${
                  step === s ? 'bg-[var(--btn-primary)] text-white shadow-sm' : 
                  step > s ? 'bg-[var(--accent-green)] text-white' : 'bg-[var(--input-bg)] text-[var(--text-muted)] border border-[var(--border)]'
                }`}>
                  {step > s ? <CheckCircle2 size={14} /> : s}
                </div>
                <span className={`text-[11px] font-bold hidden sm:block ${step >= s ? 'text-[var(--text-main)]' : 'text-[var(--text-muted)]'}`}>
                  {s === 1 ? 'Details' : s === 2 ? 'Location' : 'Admin'}
                </span>
                {s < 3 && <ChevronRight size={14} className="text-[var(--border)]" />}
              </div>
            ))}
          </div>

          <div> {/* Changed from form to div for manual control */}
            <AnimatePresence mode="wait">
              {step === 1 && (
                <motion.div key="1" initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -10 }} className="space-y-4">
                  <IconicInput icon={Building2} label="Company Name *" value={formData.company.name} onChange={(e) => setFormData({...formData, company: {...formData.company, name: e.target.value}})} />
                  <div className="grid grid-cols-2 gap-4">
                    <IconicInput icon={Globe} label="Domain" value={formData.company.domain} onChange={(e) => setFormData({...formData, company: {...formData.company, domain: e.target.value}})} />
                    <IconicInput icon={Briefcase} label="Owner" value={formData.company.owner} onChange={(e) => setFormData({...formData, company: {...formData.company, owner: e.target.value}})} />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <IconicInput icon={Mail} label="Company Email" type="email" value={formData.company.email} onChange={(e) => setFormData({...formData, company: {...formData.company, email: e.target.value}})} />
                    <IconicInput icon={Phone} label="Company Contact" value={formData.company.contact} onChange={(e) => setFormData({...formData, company: {...formData.company, contact: e.target.value}})} />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1">
                      <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Industry</label>
                      <select className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md outline-none text-[13px] font-medium text-[var(--text-main)]" value={formData.company.company_type} onChange={(e) => setFormData({...formData, company: {...formData.company, company_type: e.target.value}})}>
                        <option>Manufacturing</option><option>Retail</option><option>Tech</option><option>Pharma</option><option>Service</option><option>Other</option>
                      </select>
                    </div>
                    <IconicInput icon={Users} type="number" label="Staff Size" value={formData.company.members_count} onChange={(e) => setFormData({...formData, company: {...formData.company, members_count: parseInt(e.target.value) || 0}})} />
                  </div>
                </motion.div>
              )}
              {step === 2 && (
                <motion.div key="2" initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -10 }} className="space-y-4">
                  <IconicInput icon={MapPin} label="Street Address" value={formData.company.address} onChange={(e) => setFormData({...formData, company: {...formData.company, address: e.target.value}})} />
                  <div className="grid grid-cols-2 gap-4">
                    <IconicInput icon={Globe} label="City" value={formData.company.city} onChange={(e) => setFormData({...formData, company: {...formData.company, city: e.target.value}})} />
                    <IconicInput icon={Globe} label="State" value={formData.company.state} onChange={(e) => setFormData({...formData, company: {...formData.company, state: e.target.value}})} />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <IconicInput icon={Hash} label="GSTIN" value={formData.company.gst} onChange={(e) => setFormData({...formData, company: {...formData.company, gst: e.target.value}})} />
                    <IconicInput icon={Hash} label="PIN Code" value={formData.company.pin} onChange={(e) => setFormData({...formData, company: {...formData.company, pin: e.target.value}})} />
                  </div>
                </motion.div>
              )}
              {step === 3 && (
                <motion.div key="3" initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -10 }} className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <IconicInput icon={User} label="First Name" value={formData.admin.first_name} onChange={(e) => setFormData({...formData, admin: {...formData.admin, first_name: e.target.value}})} />
                    <IconicInput icon={User} label="Last Name" value={formData.admin.last_name} onChange={(e) => setFormData({...formData, admin: {...formData.admin, last_name: e.target.value}})} />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <IconicInput icon={Mail} label="Work Email *" type="email" value={formData.admin.email} onChange={(e) => setFormData({...formData, admin: {...formData.admin, email: e.target.value}})} />
                    <IconicInput icon={Phone} label="Mobile Number" value={formData.admin.mobile} onChange={(e) => setFormData({...formData, admin: {...formData.admin, mobile: e.target.value}})} />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <IconicInput icon={Lock} type="password" label="Temp Password *" value={formData.admin.password} onChange={(e) => setFormData({...formData, admin: {...formData.admin, password: e.target.value}})} />
                    <IconicInput icon={Briefcase} label="Designation" value={formData.admin.designation} onChange={(e) => setFormData({...formData, admin: {...formData.admin, designation: e.target.value}})} />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1">
                      <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Session Type</label>
                      <select className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md outline-none text-[13px] font-medium text-[var(--text-main)]" value={formData.admin.session_type} onChange={(e) => setFormData({...formData, admin: {...formData.admin, session_type: e.target.value}})}>
                        <option value="Core">Core</option>
                        <option value="Support">Support</option>
                        <option value="Both">Both</option>
                        <option value="None">None</option>
                      </select>
                    </div>
                    <div className="space-y-1">
                      <label className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Department</label>
                      <select className="w-full px-3 py-1.5 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-md outline-none text-[13px] font-medium text-[var(--text-main)]" value={formData.admin.department} onChange={(e) => setFormData({...formData, admin: {...formData.admin, department: e.target.value}})}>
                        <option value="HOD">HOD</option>
                        <option value="Implementor">Implementor</option>
                        <option value="EA">EA</option>
                        <option value="MD">MD</option>
                        <option value="HR">HR</option>
                        <option value="Other">Other</option>
                      </select>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            <div className="flex gap-3 mt-10 mb-2">
              {step > 1 && <button type="button" onClick={prevStep} className="px-6 py-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:border-[var(--accent-indigo)] transition-all">Back</button>}
              {step < 3 ? (
                <button type="button" onClick={nextStep} className="flex-1 py-2 bg-[var(--btn-primary)] text-white rounded-lg text-[13px] font-bold hover:bg-[var(--btn-primary-hover)] shadow-sm transition-all">Continue</button>
              ) : (
                <button type="button" onClick={handleOnboard} className="flex-1 py-2 bg-[var(--accent-green)] text-white rounded-lg text-[13px] font-bold hover:opacity-90 shadow-sm transition-all">Complete Onboarding</button>
              )}
            </div>
          </div> {/* Changed from form end to div end */}
        </div>
      </Modal>
    </div>
  );
};

export default CompanyManagement;
