import React, { useState, useEffect } from 'react';
import { useAuth } from '../../context/AuthContext';
import api from '../../services/api';
import {
  ClipboardList, Calendar, CheckCircle2, AlertCircle,
  Lock, Save, Award, ChevronRight, Check, X, ShieldAlert,
  FileDown, FileUp
} from 'lucide-react';
import {  AnimatePresence , motion } from 'framer-motion';
import * as XLSX from 'xlsx';

const ORMSheet = () => {
  useAuth();
  const [parameters, setParameters] = useState([]);
  const [selectedSub, setSelectedSub] = useState(null);
  const [selectedParamId, setSelectedParamId] = useState(null);
  
  // Period Selection
  const [periodType, setPeriodType] = useState('monthly'); // 'monthly' or 'quarterly'
  const [period, setPeriod] = useState('');
  const [periodOptions, setPeriodOptions] = useState([]);
  
  // Checklist responses
  const [responses, setResponses] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [alreadySubmitted, setAlreadySubmitted] = useState(false);
  const [submittedByMe, setSubmittedByMe] = useState(true);
  const [submittedByName, setSubmittedByName] = useState('');
  const [_submittedData, _setSubmittedData] = useState(null);
  const [errorMsg, setErrorMsg] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  // 1. Generate Period Options based on current date
  useEffect(() => {
    const options = [];
    const now = new Date();
    const currentYear = now.getFullYear();
    const currentMonth = now.getMonth(); // 0-indexed

    if (periodType === 'monthly') {
      // Last 3 months
      for (let i = 0; i < 3; i++) {
        let m = currentMonth - i;
        let y = currentYear;
        if (m < 0) {
          m += 12;
          y -= 1;
        }
        const monthStr = String(m + 1).padStart(2, '0');
        const label = new Date(y, m).toLocaleString('default', { month: 'long', year: 'numeric' });
        options.push({ value: `${y}-${monthStr}`, label });
      }
    } else {
      // Quarterly: Current & last 2 quarters
      const currentQuarter = Math.floor(currentMonth / 3) + 1;
      for (let i = 0; i < 3; i++) {
        let q = currentQuarter - i;
        let y = currentYear;
        if (q <= 0) {
          q += 4;
          y -= 1;
        }
        options.push({ value: `${y}-Q${q}`, label: `Quarter ${q}, ${y}` });
      }
    }
    setPeriodOptions(options);
    setPeriod(options[0]?.value || '');
  }, [periodType]);

  // 2. Fetch assigned parameters and subsections
  const fetchAssigned = async () => {
    setIsLoading(true);
    setErrorMsg('');
    try {
      const res = await api.get('/orm/sheet/assigned');
      const params = res.data.parameters || [];
      setParameters(params);
      
      // Auto-select the first subsection found
      if (params.length > 0) {
        for (const p of params) {
          if (p.subsections && p.subsections.length > 0) {
            setSelectedParamId(p.id);
            setSelectedSub(p.subsections[0]);
            break;
          }
        }
      }
    } catch (err) {
      console.error('Error fetching assigned ORM sheets:', err);
      setErrorMsg('Failed to load assigned ORM parameters. Please check your network connection.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchAssigned();
  }, []);

  const isBudget = selectedParamId === 'p5';
  const isEngagement = selectedParamId === 'p4';
  const isRevenue = selectedParamId === 'p1';
  const isNps = selectedParamId === 'p3';

  // Filter parameters/subsections by selected period frequency (monthly | quarterly)
  const filteredParameters = parameters
    .map(p => ({ ...p, subsections: (p.subsections || []).filter(s => s.frequency === periodType) }))
    .filter(p => p.subsections.length > 0);

  // When period type changes, reset selection to first matching subsection (or clear)
  useEffect(() => {
    if (filteredParameters.length === 0) {
      setSelectedParamId(null);
      setSelectedSub(null);
      return;
    }
    const stillValid = filteredParameters.some(p =>
      p.id === selectedParamId && p.subsections.some(s => s.id === selectedSub?.id)
    );
    if (!stillValid) {
      const first = filteredParameters[0];
      setSelectedParamId(first.id);
      setSelectedSub(first.subsections[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [periodType, parameters]);

  // 3. Fetch Submission Status for selected sub and period
  const checkSubmissionStatus = async () => {
    if (!selectedSub || !period) return;
    try {
      const res = await api.get('/orm/sheet/submission-status', {
        params: {
          parameter_id: selectedParamId,
          subsection_id: selectedSub.id,
          period: period
        }
      });
      setAlreadySubmitted(res.data.already_submitted);
      setSubmittedByMe(res.data.submitted_by_me !== false);
      setSubmittedByName(res.data.submitted_by_name || '');
      
      if (res.data.already_submitted && res.data.submission) {
        setResponses(res.data.submission.checklist || []);
      } else {
        if (isBudget) {
          const checklist = selectedSub.budgetAdherenceChecklist || [];
          setResponses(
            checklist.map(item => ({
              sno: item.sno,
              particulars: item.particulars || '',
              head: item.head || '',
              subhead: item.subhead || '',
              rate: item.rate || 0,
              target: item.target || 0,
              actual: item.actual || 0,
              gap: item.gap || 0,
              raised_by: item.raised_by || '',
              raised_to: item.raised_to || '',
              reason: item.reason || ''
            }))
          );
        } else if (isEngagement) {
          const checklist = selectedSub.teamEngagementChecklist || [];
          setResponses(
            checklist.map(item => ({
              sno: item.sno,
              question: item.question || '',
              min_marks: item.min_marks || 0,
              marks_given: item.marks_given || 0,
              review: item.review || ''
            }))
          );
        } else if (isRevenue) {
          setResponses([{
            sno: 1,
            target: parseFloat(selectedSub.target) || 0,
            achievement: 0,
            remarks: ''
          }]);
        } else if (isNps) {
          setResponses([{
            sno: 1,
            target: parseFloat(selectedSub.target) || 0,
            achievement: 0,
            sheet_id: '',
            form_id: '',
            remarks: ''
          }]);
        } else {
          const checklist = selectedSub.auditChecklist || [];
          setResponses(
            checklist.map(item => ({
              sno: item.sno,
              checkpoint: item.checkpoint,
              max_marks: item.max_marks || 5.0,
              response: 'No', // Default Yes/No
              remarks: ''
            }))
          );
        }
      }
    } catch (err) {
      console.error('Error checking submission status:', err);
    }
  };

  useEffect(() => {
    checkSubmissionStatus();
    setSuccessMsg('');
    setErrorMsg('');
  }, [selectedSub, period]);

  // Handle Yes/No Toggle
  const handleResponseChange = (index, val) => {
    if (alreadySubmitted) return;
    setResponses(prev => {
      const next = [...prev];
      next[index] = { ...next[index], response: val };
      return next;
    });
  };

  // Handle Remarks Change
  const handleRemarksChange = (index, val) => {
    if (alreadySubmitted) return;
    setResponses(prev => {
      const next = [...prev];
      next[index] = { ...next[index], remarks: val };
      return next;
    });
  };

  // Handle Team Engagement fields change
  const updateEngagementRow = (index, field, value) => {
    if (alreadySubmitted) return;
    setResponses(prev => {
      const next = [...prev];
      let val = value;
      if (field === 'marks_given') {
        val = parseFloat(value) || 0;
        const maxMarks = parseFloat(next[index].min_marks) || 0;
        if (val < 0) val = 0;
        if (val > maxMarks) val = maxMarks;
      }
      next[index] = { ...next[index], [field]: val };
      return next;
    });
  };

  // Handle Revenue field change (achievement, remarks)
  const updateRevenueRow = (field, value) => {
    if (alreadySubmitted) return;
    setResponses(prev => {
      const next = [...prev];
      if (next.length === 0) return prev;
      next[0] = { ...next[0], [field]: value };
      return next;
    });
  };

  // Handle NPS / CSI field change (achievement, sheet_id, form_id, remarks)
  const updateNpsRow = (field, value) => {
    if (alreadySubmitted) return;
    setResponses(prev => {
      const next = [...prev];
      if (next.length === 0) return prev;
      next[0] = { ...next[0], [field]: value };
      return next;
    });
  };

  // Handle Budget fields change
  const updateBudgetRow = (index, field, value) => {
    if (alreadySubmitted) return;
    setResponses(prev => {
      const next = [...prev];
      const updatedRow = { ...next[index], [field]: value };
      if (field === 'actual') {
        const targetVal = parseFloat(updatedRow.target) || 0;
        const actualVal = parseFloat(value) || 0;
        updatedRow.gap = parseFloat((targetVal - actualVal).toFixed(2));
      }
      next[index] = updatedRow;
      return next;
    });
  };

  // ─── Excel template: download a format shaped to this subsection, upload to fill ───
  // Builds the {headers, rows} for the current parameter type from the live responses
  // (which are seeded from the company's ORM design), so the template matches the setup.
  const buildExportSheet = () => {
    if (isBudget) {
      const headers = ['S.No', 'Particulars', 'Particulars Head', 'Head Subhead', 'Rate', 'Target', 'Actual', 'Gap', 'Raised By', 'Raised To', 'Reason'];
      const rows = responses.map(r => ({
        'S.No': r.sno, 'Particulars': r.particulars || '', 'Particulars Head': r.head || '', 'Head Subhead': r.subhead || '',
        'Rate': r.rate || 0, 'Target': r.target || 0, 'Actual': r.actual ?? '', 'Gap': r.gap ?? 0,
        'Raised By': r.raised_by || '', 'Raised To': r.raised_to || '', 'Reason': r.reason || ''
      }));
      return { headers, rows };
    }
    if (isEngagement) {
      const headers = ['S.No', 'Question', 'Min Marks', 'Marks Given', 'Review'];
      const rows = responses.map(r => ({ 'S.No': r.sno, 'Question': r.question || '', 'Min Marks': r.min_marks || 0, 'Marks Given': r.marks_given ?? '', 'Review': r.review || '' }));
      return { headers, rows };
    }
    if (isRevenue) {
      const headers = ['Target', 'Achievement', 'Remarks'];
      const r = responses[0] || {};
      return { headers, rows: [{ 'Target': r.target || 0, 'Achievement': r.achievement ?? '', 'Remarks': r.remarks || '' }] };
    }
    if (isNps) {
      const headers = ['Target', 'Achievement', 'Google Sheet ID', 'Google Form ID', 'Remarks'];
      const r = responses[0] || {};
      return { headers, rows: [{ 'Target': r.target || 0, 'Achievement': r.achievement ?? '', 'Google Sheet ID': r.sheet_id || '', 'Google Form ID': r.form_id || '', 'Remarks': r.remarks || '' }] };
    }
    // Process score (default audit checklist)
    const headers = ['S.No', 'Check Points', 'MM', 'Yes / No', 'Remarks'];
    const rows = responses.map(r => ({ 'S.No': r.sno, 'Check Points': r.checkpoint || '', 'MM': r.max_marks || 0, 'Yes / No': r.response || 'No', 'Remarks': r.remarks || '' }));
    return { headers, rows };
  };

  const handleExportTemplate = () => {
    const { headers, rows } = buildExportSheet();
    const data = rows.length ? rows : [Object.fromEntries(headers.map(h => [h, '']))];
    const ws = XLSX.utils.json_to_sheet(data, { header: headers });
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'ORM Data');
    const safeName = `${selectedSub?.name || 'ORM'}_${period}`.replace(/[^\w-]+/g, '_');
    XLSX.writeFile(wb, `${safeName}_Template.xlsx`);
  };

  // Merge uploaded rows onto the existing responses. Structural fields (checkpoints,
  // questions, targets, rates) stay from the config; only doer-entered values are taken
  // from the file so the upload can't tamper with the company's ORM design.
  const applyImportedRows = (imported) => {
    if (alreadySubmitted) return;
    const pick = (row, ...keys) => {
      for (const k of keys) {
        if (row[k] !== undefined && row[k] !== null && row[k] !== '') return row[k];
      }
      return undefined;
    };

    if (isRevenue || isNps) {
      const row = imported[0] || {};
      setResponses(prev => {
        const base = prev[0] || { sno: 1, target: parseFloat(selectedSub?.target) || 0 };
        const next = { ...base, achievement: parseFloat(pick(row, 'Achievement')) || 0 };
        const remarks = pick(row, 'Remarks');
        if (remarks !== undefined) next.remarks = remarks;
        if (isNps) {
          const sheetId = pick(row, 'Google Sheet ID', 'Sheet ID', 'sheet_id');
          const formId = pick(row, 'Google Form ID', 'Form ID', 'form_id');
          if (sheetId !== undefined) next.sheet_id = sheetId;
          if (formId !== undefined) next.form_id = formId;
        }
        return [next];
      });
      setSuccessMsg('Data imported from Excel. Review the values, then Submit to lock.');
      return;
    }

    setResponses(prev => prev.map((r, idx) => {
      const match = imported.find(row => String(pick(row, 'S.No', 'sno') ?? '').trim() === String(r.sno).trim()) || imported[idx] || {};
      if (isBudget) {
        const target = parseFloat(r.target) || 0;
        const actual = parseFloat(pick(match, 'Actual')) || 0;
        return {
          ...r,
          actual,
          gap: parseFloat((target - actual).toFixed(2)),
          raised_by: pick(match, 'Raised By') ?? r.raised_by,
          raised_to: pick(match, 'Raised To') ?? r.raised_to,
          reason: pick(match, 'Reason') ?? r.reason,
        };
      }
      if (isEngagement) {
        const max = parseFloat(r.min_marks) || 0;
        let mg = parseFloat(pick(match, 'Marks Given')) || 0;
        mg = Math.max(0, Math.min(max, mg));
        return { ...r, marks_given: mg, review: pick(match, 'Review') ?? r.review };
      }
      // Process score
      const raw = pick(match, 'Yes / No', 'Yes/No', 'Response');
      const response = raw !== undefined ? (String(raw).trim().toLowerCase().startsWith('y') ? 'Yes' : 'No') : r.response;
      return { ...r, response, remarks: pick(match, 'Remarks') ?? r.remarks };
    }));
    setSuccessMsg('Data imported from Excel. Review the values, then Submit to lock.');
  };

  const handleImportTemplate = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setErrorMsg('');
    const reader = new FileReader();
    reader.onload = (evt) => {
      try {
        const wb = XLSX.read(evt.target.result, { type: 'binary' });
        const ws = wb.Sheets[wb.SheetNames[0]];
        const rows = XLSX.utils.sheet_to_json(ws, { defval: '' });
        applyImportedRows(rows);
      } catch (err) {
        console.error('Import failed:', err);
        setErrorMsg('Could not read the Excel file. Please use the downloaded format template.');
      }
    };
    reader.readAsBinaryString(file);
    e.target.value = '';
  };

  // Compute live scores
  const totalMaxMarks = responses.reduce((acc, r) => acc + (parseFloat(r.max_marks) || 0), 0);
  const totalObtainedMarks = responses.reduce((acc, r) => {
    if (r.response === 'Yes') {
      return acc + (parseFloat(r.max_marks) || 0);
    }
    return acc;
  }, 0);

  // Engagement live scores
  const totalEngagementMin = responses.reduce((acc, r) => acc + (parseFloat(r.min_marks) || 0), 0);
  const totalEngagementGiven = responses.reduce((acc, r) => acc + (parseFloat(r.marks_given) || 0), 0);

  // Handle Submission
  const handleSubmit = async () => {
    if (responses.length === 0) {
      setErrorMsg('Cannot submit an empty sheet. Please contact your Client Administrator to set up checkpoints.');
      return;
    }
    
    setIsSubmitting(true);
    setErrorMsg('');
    setSuccessMsg('');
    
    try {
      await api.post('/orm/sheet/submit', {
        parameter_id: selectedParamId,
        subsection_id: selectedSub.id,
        period: period,
        checklist: responses
      });
      
      setSuccessMsg(`🎉 ORM Sheet submitted successfully for ${period}! Score: ${totalObtainedMarks} / ${totalMaxMarks}`);
      setAlreadySubmitted(true);
      
      // Refresh configurations in background to sync the Perform Matrix local state
      fetchAssigned();
    } catch (err) {
      console.error('Submission error:', err);
      setErrorMsg(err.response?.data?.detail || 'Failed to submit ORM Sheet. Please try again.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const hasContent = isBudget
    ? (responses.length > 0 || (selectedSub?.budgetAdherenceChecklist && selectedSub.budgetAdherenceChecklist.length > 0))
    : isEngagement
      ? (responses.length > 0 || (selectedSub?.teamEngagementChecklist && selectedSub.teamEngagementChecklist.length > 0))
      : isRevenue || isNps
        ? !!selectedSub
        : (selectedSub?.auditChecklist && selectedSub.auditChecklist.length > 0);
  
  const totalAdherenceScore = () => {
    if (responses.length === 0) return 0;
    const scores = responses.map(item => {
      const target = parseFloat(item.target) || 0;
      const actual = parseFloat(item.actual) || 0;
      const gap = target - actual;
      if (target === 0) return actual === 0 ? 100 : 0;
      const adherence = (1 - Math.abs(gap) / target) * 100;
      return Math.max(0, Math.min(100, adherence));
    });
    return (scores.reduce((acc, s) => acc + s, 0) / scores.length).toFixed(1);
  };

  if (isLoading) {
    return (
      <div className="p-8 flex justify-center items-center min-h-[60vh]">
        <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-8 bg-[var(--bg-main)] min-h-screen">
      {/* Top Banner */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-[var(--border)] pb-6">
        <div>
          <h1 className="text-3xl font-black text-[var(--text-main)] flex items-center gap-3">
            <ClipboardList className="text-purple-500" size={32} />
            ORM Assessment Sheet
          </h1>
          <p className="text-[var(--text-muted)] mt-1 font-bold">Submit periodic checklists and audit scores for your assigned subsections</p>
        </div>

        {/* Global Period Selector */}
        <div className="flex items-center gap-3 bg-[var(--bg-card)] border border-[var(--border)] p-2 rounded-2xl shadow-sm">
          <div className="flex bg-[var(--input-bg)] rounded-xl p-1">
            <button 
              onClick={() => setPeriodType('monthly')}
              className={`px-3 py-1.5 rounded-lg text-[10px] font-black uppercase transition-all ${periodType === 'monthly' ? 'bg-purple-600 text-white shadow-md' : 'text-[var(--text-muted)]'}`}
            >
              Monthly
            </button>
            <button 
              onClick={() => setPeriodType('quarterly')}
              className={`px-3 py-1.5 rounded-lg text-[10px] font-black uppercase transition-all ${periodType === 'quarterly' ? 'bg-purple-600 text-white shadow-md' : 'text-[var(--text-muted)]'}`}
            >
              Quarterly
            </button>
          </div>
          
          <select 
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="bg-[var(--bg-card)] border-none text-xs font-black text-[var(--text-main)] outline-none focus:ring-0 cursor-pointer pr-8"
          >
            {periodOptions.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      </div>

      {filteredParameters.length === 0 ? (
        <div className="p-12 text-center bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] max-w-xl mx-auto space-y-4">
          <div className="w-16 h-16 bg-purple-500/10 text-purple-500 rounded-full flex items-center justify-center mx-auto">
            <ShieldAlert size={32} />
          </div>
          <h2 className="text-lg font-black text-[var(--text-main)] uppercase tracking-wider">
            {parameters.length === 0 ? 'No Assigned Subsections' : `No ${periodType === 'monthly' ? 'Monthly' : 'Quarterly'} Subsections`}
          </h2>
          <p className="text-xs font-bold text-[var(--text-muted)] leading-relaxed">
            {parameters.length === 0
              ? 'You are not currently assigned to any parameters or subsections in the company ORM matrix. Please contact your Client Administrator to manage assignments.'
              : `None of your assigned subsections are configured with ${periodType} frequency. Switch the period type above or contact your Client Administrator.`}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          {/* Left Panel: Assigned Menu */}
          <div className="lg:col-span-4 space-y-4">
            <span className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] ml-2">Assigned Tasks</span>
            <div className="space-y-3">
              {filteredParameters.map((param) => (
                <div key={param.id} className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-4 space-y-2.5 shadow-sm">
                  <div className="flex items-center justify-between border-b border-[var(--border)] pb-2">
                    <span className="text-[10px] font-black uppercase text-purple-600 tracking-wider truncate max-w-[200px]">{param.name}</span>
                    <span className="text-[9px] font-black text-[var(--text-muted)]">Weight: {param.weightage}%</span>
                  </div>
                  <div className="space-y-1.5">
                    {param.subsections.map((sub) => (
                      <button
                        key={sub.id}
                        onClick={() => {
                          setSelectedParamId(param.id);
                          setSelectedSub(sub);
                        }}
                        className={`w-full flex items-center justify-between p-3 rounded-xl border text-left transition-all ${
                          selectedSub?.id === sub.id 
                            ? 'bg-purple-500/10 border-purple-500/30 text-purple-700 shadow-md font-bold' 
                            : 'bg-[var(--bg-card)]/50 border-transparent hover:bg-[var(--input-bg)]/30 text-[var(--text-muted)]'
                        }`}
                      >
                        <div className="flex flex-col gap-0.5">
                          <span className="text-xs font-black text-[var(--text-main)]">{sub.name}</span>
                          <span className="text-[9px] font-bold opacity-60">Frequency: {sub.frequency || 'None'}</span>
                        </div>
                        <ChevronRight size={14} className={selectedSub?.id === sub.id ? 'translate-x-0.5 text-purple-600' : 'opacity-40'} />
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Right Panel: Checklist / Response Sheet */}
          <div className="lg:col-span-8 space-y-6">
            {selectedSub && (
              <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-[32px] overflow-hidden shadow-md flex flex-col min-h-[500px]">
                {/* Section Header */}
                <div className="p-6 border-b border-[var(--border)] bg-[var(--input-bg)]/20 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                  <div>
                    <h2 className="text-xl font-black text-[var(--text-main)] uppercase tracking-wider">{selectedSub.name}</h2>
                    <span className="text-[10px] font-black uppercase text-purple-600 tracking-widest mt-1 block">
                      Target Score: {selectedSub.target}% | Subsection Weight: {selectedSub.weightage}%
                    </span>
                  </div>
                  
                  <div className="flex items-center gap-2">
                    <Calendar size={14} className="text-purple-500" />
                    <span className="text-xs font-black text-[var(--text-main)] bg-[var(--input-bg)] px-3 py-1 rounded-xl uppercase">
                      Period: {period}
                    </span>
                  </div>
                </div>

                {/* Main Body */}
                <div className="p-6 flex-1 flex flex-col">
                  {/* Banner Messages */}
                  <AnimatePresence>
                    {errorMsg && (
                      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="p-4 mb-4 bg-red-500/10 border border-red-500/20 rounded-2xl flex items-center gap-3 text-red-500 text-xs font-black">
                        <AlertCircle size={16} />
                        <span>{errorMsg}</span>
                      </motion.div>
                    )}
                    {successMsg && (
                      <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="p-4 mb-4 bg-green-500/10 border border-green-500/20 rounded-2xl flex items-center gap-3 text-green-600 text-xs font-black">
                        <CheckCircle2 size={16} />
                        <span>{successMsg}</span>
                      </motion.div>
                    )}
                  </AnimatePresence>

                  {alreadySubmitted ? (
                    /* Lock Screen: Already Submitted View */
                    submittedByMe ? (
                      <div className="flex-1 flex flex-col items-center justify-center text-center p-8 space-y-6">
                        <div className="w-20 h-20 bg-green-500/10 border border-green-500/20 text-green-500 rounded-full flex items-center justify-center animate-bounce">
                          <Award size={40} />
                        </div>
                        <div className="space-y-2 max-w-md">
                          <h3 className="text-lg font-black text-[var(--text-main)] uppercase tracking-wider">Assessment Submitted Successfully</h3>
                          <p className="text-xs font-bold text-[var(--text-muted)] leading-relaxed">
                            Your response has already been submitted and locked for the period <strong className="text-purple-600">{period}</strong>. 
                            The performance score is aggregate-synchronized automatically to the Matrix dashboard.
                          </p>
                        </div>
                        
                        <div className="bg-[var(--input-bg)]/30 border border-[var(--border)] px-6 py-4 rounded-2xl flex items-center gap-2">
                          <Lock size={16} className="text-amber-500" />
                          <span className="text-xs font-black text-[var(--text-main)] uppercase tracking-widest">Read-Only Periodic Lock Enabled</span>
                        </div>
                      </div>
                    ) : (
                      <div className="flex-1 flex flex-col items-center justify-center text-center p-8 space-y-6">
                        <div className="w-20 h-20 bg-amber-500/10 border border-amber-500/20 text-amber-500 rounded-full flex items-center justify-center animate-pulse">
                          <ShieldAlert size={40} />
                        </div>
                        <div className="space-y-2 max-w-md">
                          <h3 className="text-lg font-black text-[var(--text-main)] uppercase tracking-wider">Assessment Sheet Locked</h3>
                          <p className="text-xs font-bold text-[var(--text-muted)] leading-relaxed">
                            This assessment has already been completed and locked by <strong className="text-purple-600">{submittedByName}</strong> for the period <strong className="text-purple-600">{period}</strong>.
                          </p>
                          <p className="text-[10px] font-bold text-[var(--text-muted)] leading-relaxed">
                            Since only one doer can submit the assessment per period, you cannot overwrite or modify this response.
                          </p>
                        </div>
                        
                        <div className="bg-[var(--input-bg)]/30 border border-[var(--border)] px-6 py-4 rounded-2xl flex items-center gap-2">
                          <Lock size={16} className="text-red-500" />
                          <span className="text-xs font-black text-red-500 uppercase tracking-widest">Locked by peer doer</span>
                        </div>
                      </div>
                    )
                  ) : hasContent ? (
                    /* Editable Form View */
                    <div className="flex-1 flex flex-col justify-between space-y-6">
                      {/* Excel Template Toolbar: download format shaped to this subsection, upload filled data */}
                      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 bg-[var(--input-bg)]/20 border border-[var(--border)] rounded-2xl px-4 py-3">
                        <div className="flex items-center gap-2">
                          <FileDown size={14} className="text-purple-500" />
                          <span className="text-[10px] font-black uppercase tracking-wider text-[var(--text-muted)]">
                            Bulk entry — download the format, fill it offline, and upload
                          </span>
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={handleExportTemplate}
                            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-[10px] font-black uppercase tracking-wider shadow-lg shadow-blue-500/20 transition-all"
                          >
                            <FileDown size={13} /> Download Format
                          </button>
                          <label className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-[10px] font-black uppercase tracking-wider shadow-lg shadow-emerald-500/20 cursor-pointer transition-all">
                            <FileUp size={13} /> Upload Filled
                            <input type="file" className="hidden" accept=".xlsx, .xls" onChange={handleImportTemplate} />
                          </label>
                        </div>
                      </div>

                      <div className="overflow-x-auto">
                        {isBudget ? (
                          <table className="w-full text-left border-collapse min-w-[900px]">
                            <thead>
                              <tr className="text-[10px] font-black uppercase text-[var(--text-muted)] border-b border-[var(--border)]">
                                <th className="pb-3 w-12 text-center">S.No</th>
                                <th className="pb-3 px-2">Particulars</th>
                                <th className="pb-3 px-2">Particulars Head</th>
                                <th className="pb-3 px-2">Head Subhead</th>
                                <th className="pb-3 w-20 text-center">Rate</th>
                                <th className="pb-3 w-24 text-center">Target</th>
                                <th className="pb-3 w-24 text-center">Actual</th>
                                <th className="pb-3 w-24 text-center">Gap</th>
                                <th className="pb-3 px-2">Raised By</th>
                                <th className="pb-3 px-2">Raised To</th>
                                <th className="pb-3 px-2">Reason</th>
                              </tr>
                            </thead>
                            <tbody>
                              {responses.map((item, idx) => (
                                <tr key={idx} className="border-b border-[var(--border)]/50 last:border-0 hover:bg-white/5 transition-colors">
                                  <td className="py-4 text-center text-xs font-bold text-[var(--text-muted)]">{item.sno}</td>
                                  <td className="py-4 px-2 text-xs font-bold text-[var(--text-main)]">{item.particulars}</td>
                                  <td className="py-4 px-2 text-xs font-bold text-[var(--text-muted)]">{item.head}</td>
                                  <td className="py-4 px-2 text-xs font-bold text-[var(--text-muted)]">{item.subhead}</td>
                                  <td className="py-4 text-center text-xs font-bold text-[var(--text-main)]">₹{item.rate}</td>
                                  <td className="py-4 text-center text-xs font-black text-purple-600">₹{item.target}</td>
                                  <td className="py-4 text-center">
                                    <input
                                      type="number"
                                      value={item.actual || ''}
                                      onChange={(e) => updateBudgetRow(idx, 'actual', e.target.value)}
                                      disabled={alreadySubmitted}
                                      placeholder="0"
                                      className="w-20 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg px-2 py-1 text-xs font-black text-center text-[var(--text-main)] outline-none focus:border-purple-500"
                                    />
                                  </td>
                                  <td className={`py-4 text-center text-xs font-black ${(item.gap || 0) < 0 ? 'text-red-500' : 'text-green-500'}`}>
                                    ₹{item.gap || 0}
                                  </td>
                                  <td className="py-4 px-2">
                                    <input
                                      value={item.raised_by || ''}
                                      onChange={(e) => updateBudgetRow(idx, 'raised_by', e.target.value)}
                                      disabled={alreadySubmitted}
                                      placeholder="Name..."
                                      className="w-full min-w-[80px] bg-[var(--input-bg)] border border-[var(--border)] rounded-lg px-2 py-1 text-xs font-bold text-[var(--text-main)] outline-none focus:border-purple-500"
                                    />
                                  </td>
                                  <td className="py-4 px-2">
                                    <input
                                      value={item.raised_to || ''}
                                      onChange={(e) => updateBudgetRow(idx, 'raised_to', e.target.value)}
                                      disabled={alreadySubmitted}
                                      placeholder="Name..."
                                      className="w-full min-w-[80px] bg-[var(--input-bg)] border border-[var(--border)] rounded-lg px-2 py-1 text-xs font-bold text-[var(--text-main)] outline-none focus:border-purple-500"
                                    />
                                  </td>
                                  <td className="py-4 px-2">
                                    <input
                                      value={item.reason || ''}
                                      onChange={(e) => updateBudgetRow(idx, 'reason', e.target.value)}
                                      disabled={alreadySubmitted}
                                      placeholder="Reason..."
                                      className="w-full min-w-[120px] bg-[var(--input-bg)] border border-[var(--border)] rounded-lg px-2 py-1 text-xs font-bold text-[var(--text-main)] outline-none focus:border-purple-500"
                                    />
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        ) : isEngagement ? (
                          <table className="w-full text-left border-collapse min-w-[700px]">
                            <thead>
                              <tr className="text-[10px] font-black uppercase text-[var(--text-muted)] border-b border-[var(--border)]">
                                <th className="pb-3 w-12 text-center">S.No</th>
                                <th className="pb-3 px-2">Question</th>
                                <th className="pb-3 w-24 text-center">Min Marks</th>
                                <th className="pb-3 w-28 text-center">Marks Given</th>
                                <th className="pb-3 w-56 px-2">Review</th>
                              </tr>
                            </thead>
                            <tbody>
                              {responses.map((item, idx) => (
                                <tr key={idx} className="border-b border-[var(--border)]/50 last:border-0 hover:bg-white/5 transition-colors">
                                  <td className="py-4 text-center text-xs font-bold text-[var(--text-muted)]">{item.sno}</td>
                                  <td className="py-4 px-2 text-xs font-bold text-[var(--text-main)] leading-relaxed pr-6">{item.question}</td>
                                  <td className="py-4 text-center text-xs font-black text-purple-600">{item.min_marks}</td>
                                  <td className="py-4 text-center">
                                    <input
                                      type="number"
                                      value={item.marks_given ?? ''}
                                      onChange={(e) => updateEngagementRow(idx, 'marks_given', e.target.value)}
                                      disabled={alreadySubmitted}
                                      placeholder="0"
                                      min={0}
                                      max={item.min_marks}
                                      className="w-20 bg-[var(--input-bg)] border border-[var(--border)] rounded-lg px-2 py-1 text-xs font-black text-center text-[var(--text-main)] outline-none focus:border-purple-500"
                                    />
                                  </td>
                                  <td className="py-4 px-2">
                                    <input
                                      value={item.review || ''}
                                      onChange={(e) => updateEngagementRow(idx, 'review', e.target.value)}
                                      disabled={alreadySubmitted}
                                      placeholder="Add review notes..."
                                      className="w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-lg px-2 py-1 text-xs font-bold text-[var(--text-main)] outline-none focus:border-purple-500"
                                    />
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        ) : isRevenue ? (
                          <div className="space-y-5">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              <div className="bg-[var(--input-bg)]/30 border border-[var(--border)] rounded-2xl p-4">
                                <span className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">Target</span>
                                <div className="mt-1.5 text-2xl font-black text-purple-600">
                                  {selectedSub?.isPercentage ? `${responses[0]?.target ?? 0}%` : `₹${(responses[0]?.target ?? 0).toLocaleString()}`}
                                </div>
                                <span className="text-[9px] font-bold text-[var(--text-muted)] uppercase">Set in Strategic ORM Designer (read-only)</span>
                              </div>
                              <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-4">
                                <label className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">Achievement</label>
                                <input
                                  type="number"
                                  value={responses[0]?.achievement ?? ''}
                                  onChange={(e) => updateRevenueRow('achievement', e.target.value)}
                                  disabled={alreadySubmitted}
                                  placeholder="Enter achieved value..."
                                  className="mt-1.5 w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-xl px-3 py-2 text-2xl font-black text-[var(--text-main)] outline-none focus:border-purple-500"
                                />
                                <span className="text-[9px] font-bold text-[var(--text-muted)] uppercase mt-1 block">
                                  {selectedSub?.isPercentage ? 'Enter as percentage' : 'Enter raw value for this period'}
                                </span>
                              </div>
                            </div>
                            <div>
                              <label className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">Remarks</label>
                              <textarea
                                value={responses[0]?.remarks ?? ''}
                                onChange={(e) => updateRevenueRow('remarks', e.target.value)}
                                disabled={alreadySubmitted}
                                rows={3}
                                placeholder="Optional context, deviations, supporting notes..."
                                className="mt-1.5 w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-xl px-3 py-2 text-xs font-bold text-[var(--text-main)] outline-none focus:border-purple-500"
                              />
                            </div>
                          </div>
                        ) : isNps ? (
                          <div className="space-y-5">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              <div className="bg-[var(--input-bg)]/30 border border-[var(--border)] rounded-2xl p-4">
                                <span className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">Target Score</span>
                                <div className="mt-1.5 text-2xl font-black text-purple-600">
                                  {responses[0]?.target ?? 0}{selectedSub?.isPercentage ? '%' : ''}
                                </div>
                                <span className="text-[9px] font-bold text-[var(--text-muted)] uppercase">Set in Strategic ORM Designer (read-only)</span>
                              </div>
                              <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl p-4">
                                <label className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">Achievement Score</label>
                                <input
                                  type="number"
                                  value={responses[0]?.achievement ?? ''}
                                  onChange={(e) => updateNpsRow('achievement', e.target.value)}
                                  disabled={alreadySubmitted}
                                  placeholder="Enter measured NPS / CSI score..."
                                  className="mt-1.5 w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-xl px-3 py-2 text-2xl font-black text-[var(--text-main)] outline-none focus:border-purple-500"
                                />
                                <span className="text-[9px] font-bold text-[var(--text-muted)] uppercase mt-1 block">
                                  {selectedSub?.isPercentage ? 'Enter as percentage' : 'Enter raw survey score for this period'}
                                </span>
                              </div>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              <div>
                                <label className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">Google Sheet ID</label>
                                <input
                                  value={responses[0]?.sheet_id ?? ''}
                                  onChange={(e) => updateNpsRow('sheet_id', e.target.value)}
                                  disabled={alreadySubmitted}
                                  placeholder="Paste responses sheet ID or URL..."
                                  className="mt-1.5 w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-xl px-3 py-2 text-xs font-bold text-[var(--text-main)] outline-none focus:border-purple-500"
                                />
                              </div>
                              <div>
                                <label className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">Google Form ID</label>
                                <input
                                  value={responses[0]?.form_id ?? ''}
                                  onChange={(e) => updateNpsRow('form_id', e.target.value)}
                                  disabled={alreadySubmitted}
                                  placeholder="Paste survey form ID or URL..."
                                  className="mt-1.5 w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-xl px-3 py-2 text-xs font-bold text-[var(--text-main)] outline-none focus:border-purple-500"
                                />
                              </div>
                            </div>

                            <div>
                              <label className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)]">Remarks</label>
                              <textarea
                                value={responses[0]?.remarks ?? ''}
                                onChange={(e) => updateNpsRow('remarks', e.target.value)}
                                disabled={alreadySubmitted}
                                rows={3}
                                placeholder="Sample size, methodology, response rate, anomalies..."
                                className="mt-1.5 w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-xl px-3 py-2 text-xs font-bold text-[var(--text-main)] outline-none focus:border-purple-500"
                              />
                            </div>
                          </div>
                        ) : (
                          <table className="w-full text-left border-collapse min-w-[600px]">
                            <thead>
                              <tr className="text-[10px] font-black uppercase text-[var(--text-muted)] border-b border-[var(--border)]">
                                <th className="pb-3 w-12 text-center">S.No</th>
                                <th className="pb-3 px-2">Check Points</th>
                                <th className="pb-3 w-32 text-center">Yes / No</th>
                                <th className="pb-3 w-48 px-2">Remarks</th>
                              </tr>
                            </thead>
                            <tbody>
                              {responses.map((item, idx) => (
                                <tr key={idx} className="border-b border-[var(--border)]/50 last:border-0 hover:bg-white/5 transition-colors">
                                  <td className="py-4 text-center text-xs font-bold text-[var(--text-muted)]">{item.sno}</td>
                                  <td className="py-4 px-2 text-xs font-bold text-[var(--text-main)] leading-relaxed pr-6">{item.checkpoint}</td>
                                  <td className="py-4 text-center">
                                    <div className="inline-flex bg-[var(--input-bg)] border border-[var(--border)] rounded-xl p-1 shadow-inner">
                                      <button
                                        onClick={() => handleResponseChange(idx, 'Yes')}
                                        className={`px-3 py-1 rounded-lg text-[10px] font-black uppercase tracking-wider transition-all flex items-center gap-1 ${
                                          item.response === 'Yes' 
                                            ? 'bg-green-500 text-white shadow-md' 
                                            : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'
                                        }`}
                                      >
                                        <Check size={10} /> Yes
                                      </button>
                                      <button
                                        onClick={() => handleResponseChange(idx, 'No')}
                                        className={`px-3 py-1 rounded-lg text-[10px] font-black uppercase tracking-wider transition-all flex items-center gap-1 ${
                                          item.response === 'No' 
                                            ? 'bg-red-500 text-white shadow-md' 
                                            : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'
                                        }`}
                                      >
                                        <X size={10} /> No
                                      </button>
                                    </div>
                                  </td>
                                  <td className="py-4 px-2">
                                    <input
                                      value={item.remarks}
                                      onChange={(e) => handleRemarksChange(idx, e.target.value)}
                                      placeholder="Add optional remarks..."
                                      className="w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-lg px-2 py-1 text-xs font-bold text-[var(--text-main)] outline-none focus:border-purple-500"
                                    />
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </div>

                      {/* Bottom Live Score & Save Panel */}
                      <div className="pt-6 border-t border-[var(--border)] flex flex-col sm:flex-row justify-between items-center gap-4 bg-[var(--input-bg)]/20 -mx-6 -mb-6 p-6">
                        {isBudget ? (
                          <div className="flex items-center gap-4">
                            <div className="flex flex-col">
                              <span className="text-[9px] font-black uppercase text-[var(--text-muted)] tracking-wider">Live Adherence Rate</span>
                              <span className="text-2xl font-black text-purple-600">{totalAdherenceScore()}%</span>
                            </div>
                            <div className="bg-purple-500/10 border border-purple-500/20 px-3 py-1.5 rounded-xl">
                              <span className="text-[9px] font-black uppercase tracking-tighter text-purple-700">
                                Gap = Target - Actual (Target Adherence index)
                              </span>
                            </div>
                          </div>
                        ) : isEngagement ? (
                          <div className="flex items-center gap-4">
                            <div className="flex flex-col">
                              <span className="text-[9px] font-black uppercase text-[var(--text-muted)] tracking-wider">Live Engagement Score</span>
                              <span className="text-2xl font-black text-purple-600">{totalEngagementGiven} / {totalEngagementMin}</span>
                            </div>
                            <div className="bg-purple-500/10 border border-purple-500/20 px-3 py-1.5 rounded-xl">
                              <span className="text-[9px] font-black uppercase tracking-tighter text-purple-700">
                                Marks Given (capped at Min Marks per question)
                              </span>
                            </div>
                          </div>
                        ) : isRevenue || isNps ? (() => {
                          const t = parseFloat(responses[0]?.target) || 0;
                          const a = parseFloat(responses[0]?.achievement) || 0;
                          const pct = t > 0 ? Math.min(100, (a / t) * 100) : (a === 0 ? 0 : 100);
                          return (
                            <div className="flex items-center gap-4">
                              <div className="flex flex-col">
                                <span className="text-[9px] font-black uppercase text-[var(--text-muted)] tracking-wider">Live Achievement %</span>
                                <span className="text-2xl font-black text-purple-600">{pct.toFixed(1)}%</span>
                              </div>
                              <div className="bg-purple-500/10 border border-purple-500/20 px-3 py-1.5 rounded-xl">
                                <span className="text-[9px] font-black uppercase tracking-tighter text-purple-700">
                                  Achievement / Target × 100 (capped at 100)
                                </span>
                              </div>
                            </div>
                          );
                        })() : (
                          <div className="flex items-center gap-4">
                            <div className="flex flex-col">
                              <span className="text-[9px] font-black uppercase text-[var(--text-muted)] tracking-wider">Live Obtained marks</span>
                              <span className="text-2xl font-black text-purple-600">{totalObtainedMarks} / {totalMaxMarks}</span>
                            </div>
                            
                            <div className="bg-purple-500/10 border border-purple-500/20 px-3 py-1.5 rounded-xl">
                              <span className="text-[9px] font-black uppercase tracking-tighter text-purple-700">
                                Yes: MM ({responses.length ? (totalMaxMarks / responses.length).toFixed(1) : 0} pts) | No: 0 pts
                              </span>
                            </div>
                          </div>
                        )}

                        <button
                          onClick={handleSubmit}
                          disabled={isSubmitting}
                          className={`flex items-center gap-2 px-8 py-3 bg-purple-600 hover:bg-purple-700 text-white font-black text-xs uppercase tracking-widest rounded-2xl shadow-xl shadow-purple-500/20 transition-all active:scale-95 ${
                            isSubmitting ? 'opacity-50 cursor-wait' : ''
                          }`}
                        >
                          <Save size={16} />
                          {isSubmitting ? 'Submitting...' : 'Submit Assessment'}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex-1 flex flex-col items-center justify-center text-center p-8 space-y-4">
                      <div className="w-16 h-16 bg-amber-500/10 text-amber-500 rounded-full flex items-center justify-center">
                        <AlertCircle size={28} />
                      </div>
                      <div className="space-y-1.5 max-w-sm">
                        <h3 className="text-sm font-black text-[var(--text-main)] uppercase tracking-wide">No Checklist Setup</h3>
                        <p className="text-[10px] font-bold text-[var(--text-muted)] leading-relaxed">
                          There is no active audit checklist configured for this subsection. 
                          Please contact your Client Administrator to set up process score checkpoints.
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default ORMSheet;
