import React, { useState, useEffect } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import {
  Plus, Trash2, Save, ChevronDown, ChevronRight,
  Target, BarChart3, PieChart, Info, AlertCircle, CheckCircle2,
  TrendingUp, TrendingDown, Layers, Calculator, Users, UserPlus, X,
  Calendar, Clock, BellRing, Settings2, ClipboardCheck, FileDown, FileUp,
  ExternalLink, FileText, Lock, Send
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/api';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import * as XLSX from 'xlsx';
import { jsPDF } from 'jspdf';
import autoTable from 'jspdf-autotable';
import { sanitizeORMParameters } from '../../utils/ormSanitize';

const AuditModal = ({ isOpen, onClose, subsection, onSave, paramId, paramName }) => {
  const [checklist, setChecklist] = useState(subsection.auditChecklist || []);
  const [unitName, setUnitName] = useState(subsection.unitName || '');
  const [achievement, setAchievement] = useState(subsection.achievement || 0);
  const [remarks, setRemarks] = useState(subsection.remarks || '');
  const [googleSheetLink, setGoogleSheetLink] = useState(subsection.googleSheetLink || '');
  const [googleFormLink, setGoogleFormLink] = useState(subsection.googleFormLink || '');
  const [teamChecklist, setTeamChecklist] = useState(subsection.teamEngagementChecklist || []);
  const [surveyDoerName, setSurveyDoerName] = useState(subsection.surveyDoerName || '');
  const [surveyDoerEmail, setSurveyDoerEmail] = useState(subsection.surveyDoerEmail || '');
  const [budgetChecklist, setBudgetChecklist] = useState(subsection.budgetAdherenceChecklist || []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setChecklist(subsection.auditChecklist || []);
    setUnitName(subsection.unitName || '');
    setAchievement(subsection.achievement || 0);
    setRemarks(subsection.remarks || '');
    setGoogleSheetLink(subsection.googleSheetLink || '');
    setGoogleFormLink(subsection.googleFormLink || '');
    setTeamChecklist(subsection.teamEngagementChecklist || []);
    setSurveyDoerName(subsection.surveyDoerName || '');
    setSurveyDoerEmail(subsection.surveyDoerEmail || '');
    setBudgetChecklist(subsection.budgetAdherenceChecklist || []);
  }, [subsection]);

  const updateRow = (index, field, value) => {
    const newList = [...checklist];
    newList[index] = { ...newList[index], [field]: value };
    if (field === 'response') {
      newList[index].obtained_marks = value === 'Yes' ? newList[index].max_marks : 0;
    }
    setChecklist(newList);
  };

  const updateTeamRow = (index, field, value) => {
    const newList = [...teamChecklist];
    newList[index] = { ...newList[index], [field]: value };
    setTeamChecklist(newList);
  };

  const updateBudgetRow = (index, field, value) => {
    const newList = [...budgetChecklist];
    const updatedRow = { ...newList[index], [field]: value };
    
    if (field === 'target' || field === 'actual' || field === 'rate') {
      const targetVal = field === 'target' ? parseFloat(value) || 0 : parseFloat(updatedRow.target) || 0;
      const actualVal = field === 'actual' ? parseFloat(value) || 0 : parseFloat(updatedRow.actual) || 0;
      updatedRow.gap = parseFloat((targetVal - actualVal).toFixed(2));
    }
    
    newList[index] = updatedRow;
    setBudgetChecklist(newList);
  };

  const totalObtained = checklist.reduce((acc, item) => acc + (parseFloat(item.obtained_marks) || 0), 0);

  const handleExport = () => {
    const headers = ['S.No', 'Check Points', 'MM - 5', 'Yes/No', 'Obtained Marks', 'Remarks'];
    const data = (checklist && checklist.length > 0)
      ? checklist.map(item => ({
          'S.No': item.sno,
          'Check Points': item.checkpoint,
          'MM - 5': item.max_marks,
          'Yes/No': item.response,
          'Obtained Marks': item.obtained_marks,
          'Remarks': item.remarks
        }))
      : [Object.fromEntries(headers.map(h => [h, '']))];

    const ws = XLSX.utils.json_to_sheet(data, { header: headers });
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Audit");
    XLSX.writeFile(wb, `${subsection.name}_Audit_Template.xlsx`);
  };

  const handleImport = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      const bstr = evt.target.result;
      const wb = XLSX.read(bstr, { type: 'binary' });
      const wsname = wb.SheetNames[0];
      const ws = wb.Sheets[wsname];
      const data = XLSX.utils.sheet_to_json(ws);
      const imported = data.map(row => ({
        sno: parseInt(row['S.No']) || 0,
        checkpoint: row['Check Points'] || '',
        max_marks: parseFloat(row['MM - 5']) || 5.0,
        response: row['Yes/No'] || 'No',
        obtained_marks: parseFloat(row['Obtained Marks']) || 0.0,
        remarks: row['Remarks'] || ''
      }));
      setChecklist(imported);
    };
    reader.readAsBinaryString(file);
    e.target.value = ''; // Reset the input value so that the next select always triggers onChange!
  };

  const handleTeamExport = () => {
    const headers = ['S.No', 'Question', 'Minimum Marks', 'Review'];
    const data = (teamChecklist && teamChecklist.length > 0)
      ? teamChecklist.map(item => ({
          'S.No': item.sno,
          'Question': item.question,
          'Minimum Marks': item.min_marks,
          'Review': item.review || ''
        }))
      : [Object.fromEntries(headers.map(h => [h, '']))];

    const ws = XLSX.utils.json_to_sheet(data, { header: headers });
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Team Engagement");
    XLSX.writeFile(wb, `${subsection.name}_Team_Engagement_Audit.xlsx`);
  };

  const handleTeamImport = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      const bstr = evt.target.result;
      const wb = XLSX.read(bstr, { type: 'binary' });
      const wsname = wb.SheetNames[0];
      const ws = wb.Sheets[wsname];
      const data = XLSX.utils.sheet_to_json(ws);
      const imported = data.map(row => ({
        sno: parseInt(row['S.No']) || 0,
        question: row['Question'] || '',
        min_marks: parseFloat(row['Minimum Marks']) || 0.0,
        review: row['Review'] || ''
      }));
      setTeamChecklist(imported);
    };
    reader.readAsBinaryString(file);
    e.target.value = ''; // Reset import file selection
  };

  const handleBudgetExport = () => {
    const headers = [
      'S.No', 'Particulars', 'Particulars Head', 'Head Subhead', 
      'Rate', 'Target', 'Actual', 'Gap', 'Raised By', 'Raised To', 'Reason'
    ];
    const data = (budgetChecklist && budgetChecklist.length > 0)
      ? budgetChecklist.map(item => ({
          'S.No': item.sno,
          'Particulars': item.particulars || '',
          'Particulars Head': item.head || '',
          'Head Subhead': item.subhead || '',
          'Rate': item.rate || 0,
          'Target': item.target || 0,
          'Actual': item.actual || 0,
          'Gap': item.gap || 0,
          'Raised By': item.raised_by || '',
          'Raised To': item.raised_to || '',
          'Reason': item.reason || ''
        }))
      : [Object.fromEntries(headers.map(h => [h, '']))];

    const ws = XLSX.utils.json_to_sheet(data, { header: headers });
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Budget Adherence");
    XLSX.writeFile(wb, `${subsection.name}_Budget_Cost_Adherence_Audit.xlsx`);
  };

  const handleBudgetImport = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      const bstr = evt.target.result;
      const wb = XLSX.read(bstr, { type: 'binary' });
      const wsname = wb.SheetNames[0];
      const ws = wb.Sheets[wsname];
      const data = XLSX.utils.sheet_to_json(ws);
      const imported = data.map(row => {
        const rate = parseFloat(row['Rate']) || 0.0;
        const target = parseFloat(row['Target']) || 0.0;
        const actual = parseFloat(row['Actual']) || 0.0;
        const gap = row['Gap'] !== undefined ? parseFloat(row['Gap']) : parseFloat((target - actual).toFixed(2));
        return {
          sno: parseInt(row['S.No']) || 0,
          particulars: row['Particulars'] || '',
          head: row['Particulars Head'] || '',
          subhead: row['Head Subhead'] || '',
          rate,
          target,
          actual,
          gap,
          raised_by: row['Raised By'] || '',
          raised_to: row['Raised To'] || '',
          reason: row['Reason'] || ''
        };
      });
      setBudgetChecklist(imported);
    };
    reader.readAsBinaryString(file);
    e.target.value = '';
  };

  const isProcessScore = paramId === 'p2' || paramName === 'Process score';
  const isNpsOrCsi = paramId === 'p3' || paramName === 'NPS OR CSI';
  const isTeamEngagement = paramId === 'p4' || paramName === 'Team Engagement index';
  const isBudgetAdherence = paramId === 'p5' || paramName === 'Budget Cost Adherence';

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div 
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
          />
          <motion.div 
            initial={{ scale: 0.9, opacity: 0, y: 20 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.9, opacity: 0, y: 20 }}
            className="relative w-full max-w-4xl bg-[var(--bg-card)] rounded-[32px] border border-[var(--border)] shadow-2xl overflow-hidden flex flex-col max-h-[90vh]"
          >
            <div className="p-6 border-b border-[var(--border)] bg-[var(--input-bg)]/30 flex justify-between items-center">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-amber-500/10 rounded-xl text-amber-600">
                  <ClipboardCheck size={24} />
                </div>
                <div>
                  <h2 className="text-xl font-black text-[var(--text-main)]">{subsection.name} Audit</h2>
                  <p className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">
                    {isProcessScore ? 'Perform verification and update checklist scores' : isNpsOrCsi ? 'Verify using Google Form and Google Sheet' : 'Verify reported achievement and input verified score'}
                  </p>
                </div>
              </div>
              <button onClick={onClose} className="p-2 hover:bg-red-500/10 text-red-500 rounded-xl transition-all"><X size={20} /></button>
            </div>

            <div className="p-6 overflow-y-auto custom-scrollbar flex-1 space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-[10px] font-black uppercase text-[var(--text-muted)] ml-1">Unit Name</label>
                  <input 
                    value={unitName}
                    onChange={(e) => setUnitName(e.target.value)}
                    className="w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-xl px-4 py-2 text-sm font-bold text-[var(--text-main)]"
                    placeholder="Enter unit name..."
                  />
                </div>
                {isProcessScore && (
                  <div className="flex items-center justify-end gap-2">
                    <button onClick={handleExport} className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-xl text-xs font-black shadow-lg shadow-blue-500/20">
                      <FileDown size={14} /> Export Format
                    </button>
                    <label className="flex items-center gap-2 px-4 py-2 bg-emerald-600 text-white rounded-xl text-xs font-black shadow-lg shadow-emerald-500/20 cursor-pointer">
                      <FileUp size={14} /> Import Filled
                      <input type="file" className="hidden" accept=".xlsx, .xls" onChange={handleImport} />
                    </label>
                  </div>
                )}
                {isTeamEngagement && (
                  <div className="flex items-center justify-end gap-2">
                    <button onClick={handleTeamExport} className="flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-xl text-xs font-black shadow-lg shadow-purple-500/20 transition-all">
                      <FileDown size={14} /> Export Format
                    </button>
                    <label className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-black shadow-lg shadow-emerald-500/20 cursor-pointer transition-all">
                      <FileUp size={14} /> Import Filled
                      <input type="file" className="hidden" accept=".xlsx, .xls" onChange={handleTeamImport} />
                    </label>
                  </div>
                )}
                {isBudgetAdherence && (
                  <div className="flex items-center justify-end gap-2">
                    <button onClick={handleBudgetExport} className="flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-xl text-xs font-black shadow-lg shadow-purple-500/20 transition-all">
                      <FileDown size={14} /> Export Format
                    </button>
                    <label className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-black shadow-lg shadow-emerald-500/20 cursor-pointer transition-all">
                      <FileUp size={14} /> Import Filled
                      <input type="file" className="hidden" accept=".xlsx, .xls" onChange={handleBudgetImport} />
                    </label>
                  </div>
                )}
              </div>

              {isProcessScore ? (
                <div className="bg-[var(--input-bg)]/20 rounded-2xl border border-[var(--border)] overflow-hidden">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="text-[10px] font-black uppercase text-[var(--text-muted)] border-b border-[var(--border)] bg-[var(--input-bg)]/50">
                        <th className="p-4 w-12 text-center">S.No</th>
                        <th className="p-4">Check Points</th>
                        <th className="p-4 w-20">MM-5</th>
                        <th className="p-4 w-24">Yes/No</th>
                        <th className="p-4 w-24">Obtained</th>
                        <th className="p-4">Remarks</th>
                      </tr>
                    </thead>
                    <tbody>
                      {checklist.map((item, idx) => (
                        <tr key={idx} className="border-b border-[var(--border)]/50 last:border-0 hover:bg-white/5 transition-colors">
                          <td className="p-4 text-center text-xs font-bold text-[var(--text-muted)]">{item.sno}</td>
                          <td className="p-4 text-xs font-black text-[var(--text-main)]">{item.checkpoint}</td>
                          <td className="p-4 text-xs font-black text-blue-500">{item.max_marks}</td>
                          <td className="p-4">
                            <select 
                              value={item.response}
                              onChange={(e) => updateRow(idx, 'response', e.target.value)}
                              className="w-full bg-[var(--bg-card)] border border-[var(--border)] rounded-lg p-1.5 text-xs font-black outline-none focus:border-blue-500"
                            >
                              <option value="Yes">Yes</option>
                              <option value="No">No</option>
                            </select>
                          </td>
                          <td className="p-4">
                            <input 
                              type="number"
                              value={item.obtained_marks}
                              onChange={(e) => updateRow(idx, 'obtained_marks', e.target.value)}
                              className="w-full bg-[var(--bg-card)] border border-[var(--border)] rounded-lg p-1.5 text-xs font-black outline-none focus:border-blue-500"
                            />
                          </td>
                          <td className="p-4">
                            <input 
                              value={item.remarks}
                              onChange={(e) => updateRow(idx, 'remarks', e.target.value)}
                              className="w-full bg-transparent border-none p-0 text-[11px] font-medium text-[var(--text-muted)] focus:ring-0"
                              placeholder="Add remarks..."
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : isNpsOrCsi ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="space-y-4 bg-[var(--input-bg)]/30 p-5 rounded-2xl border border-[var(--border)]">
                    <h3 className="text-xs font-black uppercase text-purple-500 tracking-wider">Survey & Feedback Integration</h3>
                    
                    <div className="space-y-4">
                      <div className="bg-[var(--bg-card)] p-4 rounded-xl border border-[var(--border)] space-y-3">
                        <div className="flex items-center justify-between">
                          <span className="text-[10px] font-black uppercase text-[var(--text-muted)]">Google Form Link</span>
                          {googleFormLink && (
                            <a 
                              href={googleFormLink} 
                              target="_blank" 
                              rel="noopener noreferrer"
                              className="flex items-center gap-1 text-[10px] font-black text-purple-500 hover:text-purple-600 uppercase"
                            >
                              Open Form <ExternalLink size={12} />
                            </a>
                          )}
                        </div>
                        <input 
                          type="url"
                          value={googleFormLink}
                          onChange={(e) => setGoogleFormLink(e.target.value)}
                          className="w-full bg-[var(--input-bg)] border border-[var(--border)] focus:border-purple-500 rounded-lg px-3 py-1.5 text-xs font-black text-[var(--text-main)] outline-none"
                          placeholder="https://docs.google.com/forms/d/..."
                        />
                      </div>

                      <div className="bg-[var(--bg-card)] p-4 rounded-xl border border-[var(--border)] space-y-3">
                        <div className="flex items-center justify-between">
                          <span className="text-[10px] font-black uppercase text-[var(--text-muted)]">Google Sheet Link</span>
                          {googleSheetLink && (
                            <a 
                              href={googleSheetLink} 
                              target="_blank" 
                              rel="noopener noreferrer"
                              className="flex items-center gap-1 text-[10px] font-black text-emerald-500 hover:text-emerald-600 uppercase"
                            >
                              Open Sheet <ExternalLink size={12} />
                            </a>
                          )}
                        </div>
                        <input 
                          type="url"
                          value={googleSheetLink}
                          onChange={(e) => setGoogleSheetLink(e.target.value)}
                          className="w-full bg-[var(--input-bg)] border border-[var(--border)] focus:border-emerald-500 rounded-lg px-3 py-1.5 text-xs font-black text-[var(--text-main)] outline-none"
                          placeholder="https://docs.google.com/spreadsheets/d/..."
                        />
                      </div>
                    </div>
                  </div>

                  <div className="space-y-4 bg-amber-500/5 p-5 rounded-2xl border border-amber-500/10">
                    <h3 className="text-xs font-black uppercase text-amber-600 tracking-wider">Auditor Verification</h3>
                    
                    <div className="space-y-1.5">
                      <label className="text-[10px] font-black uppercase text-[var(--text-muted)] ml-1">Audited Achievement Score</label>
                      <div className="relative">
                        <input 
                          type="number"
                          value={achievement}
                          onChange={(e) => setAchievement(parseFloat(e.target.value) || 0)}
                          className="w-full bg-[var(--bg-card)] border border-[var(--border)] focus:border-amber-500 rounded-xl px-4 py-2.5 text-sm font-black text-[var(--text-main)] outline-none transition-all"
                          placeholder="Enter verified achievement..."
                        />
                        {subsection.isPercentage && (
                          <span className="absolute right-4 top-1/2 -translate-y-1/2 text-xs font-black text-blue-500 uppercase">%</span>
                        )}
                      </div>
                    </div>

                    <div className="space-y-1.5">
                      <label className="text-[10px] font-black uppercase text-[var(--text-muted)] ml-1">Verification Remarks / Comments</label>
                      <textarea 
                        value={remarks}
                        onChange={(e) => setRemarks(e.target.value)}
                        className="w-full bg-[var(--bg-card)] border border-[var(--border)] focus:border-amber-500 rounded-xl px-4 py-2 text-xs font-bold text-[var(--text-main)] outline-none min-h-[100px] transition-all resize-none"
                        placeholder="Enter audit remarks, evidence verification notes, etc..."
                      />
                    </div>
                  </div>
                </div>
              ) : isTeamEngagement ? (
                <div className="space-y-6 flex-1 flex flex-col overflow-hidden">
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="bg-purple-500/5 border border-purple-500/10 p-4 rounded-2xl flex flex-col justify-center">
                      <span className="text-[10px] font-black uppercase text-[var(--text-muted)] block mb-1">Active Survey Mode</span>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-black text-purple-600 uppercase">
                          {subsection.surveyLevel === 'anonymous' ? '🔒 Anonymous Survey' : '👤 Public Survey'}
                        </span>
                      </div>
                    </div>

                    {subsection.surveyLevel !== 'anonymous' ? (
                      <>
                        <div className="space-y-1">
                          <label className="text-[10px] font-black uppercase text-[var(--text-muted)] ml-1">Survey Respondent Name</label>
                          <input 
                            value={surveyDoerName}
                            onChange={(e) => setSurveyDoerName(e.target.value)}
                            placeholder="e.g. John Doe"
                            className="w-full bg-[var(--bg-card)] border border-[var(--border)] focus:border-purple-500 rounded-xl px-4 py-2 text-xs font-black text-[var(--text-main)] outline-none"
                          />
                        </div>
                        <div className="space-y-1">
                          <label className="text-[10px] font-black uppercase text-[var(--text-muted)] ml-1">Survey Respondent Email</label>
                          <input 
                            type="email"
                            value={surveyDoerEmail}
                            onChange={(e) => setSurveyDoerEmail(e.target.value)}
                            placeholder="e.g. john@company.com"
                            className="w-full bg-[var(--bg-card)] border border-[var(--border)] focus:border-purple-500 rounded-xl px-4 py-2 text-xs font-black text-[var(--text-main)] outline-none"
                          />
                        </div>
                      </>
                    ) : (
                      <div className="md:col-span-2 bg-[var(--input-bg)]/20 border border-[var(--border)] px-4 py-3 rounded-2xl flex items-center text-xs font-bold text-[var(--text-muted)]">
                        🔒 Identity Protection: Respondent names and emails are automatically stripped from reports to guarantee true anonymity.
                      </div>
                    )}
                  </div>

                  <div className="bg-[var(--input-bg)]/20 rounded-2xl border border-[var(--border)] overflow-hidden flex-1 flex flex-col">
                    <div className="overflow-y-auto max-h-[40vh] custom-scrollbar">
                      <table className="w-full text-left border-collapse">
                        <thead>
                          <tr className="text-[10px] font-black uppercase text-[var(--text-muted)] border-b border-[var(--border)] bg-[var(--input-bg)]/50 sticky top-0 z-10">
                            <th className="p-4 w-12 text-center">S.No</th>
                            <th className="p-4">Question</th>
                            <th className="p-4 w-28">Minimum Marks</th>
                            <th className="p-4">Review / Comments / Value</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(teamChecklist || []).map((item, idx) => (
                            <tr key={idx} className="border-b border-[var(--border)]/50 last:border-0 hover:bg-white/5 transition-colors">
                              <td className="p-4 text-center text-xs font-bold text-[var(--text-muted)]">{item.sno}</td>
                              <td className="p-4 text-xs font-black text-[var(--text-main)]">{item.question}</td>
                              <td className="p-4 text-xs font-black text-purple-600">{item.min_marks}</td>
                              <td className="p-4">
                                <input 
                                  value={item.review || ''}
                                  onChange={(e) => updateTeamRow(idx, 'review', e.target.value)}
                                  className="w-full bg-transparent border-none p-0 text-xs font-bold text-[var(--text-main)] focus:ring-0"
                                  placeholder="Input survey review, response value or remarks..."
                                />
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
                    <div className="space-y-1.5">
                      <label className="text-[10px] font-black uppercase text-[var(--text-muted)] ml-1">Verified Engagement Score</label>
                      <input 
                        type="number"
                        value={achievement}
                        onChange={(e) => setAchievement(parseFloat(e.target.value) || 0)}
                        className="w-full bg-[var(--bg-card)] border border-[var(--border)] focus:border-purple-500 rounded-xl px-4 py-2 text-sm font-black text-[var(--text-main)] outline-none"
                        placeholder="Verified team index score..."
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-[10px] font-black uppercase text-[var(--text-muted)] ml-1">Engagement Audit Remarks</label>
                      <input 
                        value={remarks}
                        onChange={(e) => setRemarks(e.target.value)}
                        className="w-full bg-[var(--bg-card)] border border-[var(--border)] focus:border-purple-500 rounded-xl px-4 py-2 text-xs font-bold text-[var(--text-main)] outline-none"
                        placeholder="Provide overall team feedback..."
                      />
                    </div>
                  </div>
                </div>
              ) : isBudgetAdherence ? (
                 <div className="space-y-6 flex-1 flex flex-col overflow-hidden">
                   <div className="bg-[var(--input-bg)]/20 rounded-2xl border border-[var(--border)] overflow-hidden flex-1 flex flex-col">
                     <div className="overflow-x-auto overflow-y-auto max-h-[40vh] custom-scrollbar">
                       <table className="min-w-[1200px] w-full text-left border-collapse">
                         <thead>
                           <tr className="text-[10px] font-black uppercase text-[var(--text-muted)] border-b border-[var(--border)] bg-[var(--input-bg)]/50 sticky top-0 z-10">
                             <th className="p-4 w-12 text-center">S.No</th>
                             <th className="p-4 w-40">Particulars</th>
                             <th className="p-4 w-36">Particulars Head</th>
                             <th className="p-4 w-36">Head Subhead</th>
                             <th className="p-4 w-20">Rate</th>
                             <th className="p-4 w-20">Target</th>
                             <th className="p-4 w-20">Actual</th>
                             <th className="p-4 w-20">Gap</th>
                             <th className="p-4 w-28">Raised By</th>
                             <th className="p-4 w-28">Raised To</th>
                             <th className="p-4 w-40">Reason</th>
                           </tr>
                         </thead>
                         <tbody>
                           {(budgetChecklist || []).map((item, idx) => (
                             <tr key={idx} className="border-b border-[var(--border)]/50 last:border-0 hover:bg-white/5 transition-colors">
                               <td className="p-4 text-center text-xs font-bold text-[var(--text-muted)]">{item.sno}</td>
                               <td className="p-4 text-xs font-black text-[var(--text-main)]">{item.particulars}</td>
                               <td className="p-4 text-xs font-black text-[var(--text-main)]">{item.head}</td>
                               <td className="p-4 text-xs font-black text-[var(--text-main)]">{item.subhead}</td>
                               <td className="p-4">
                                 <input 
                                   type="number"
                                   value={item.rate}
                                   onChange={(e) => updateBudgetRow(idx, 'rate', parseFloat(e.target.value) || 0)}
                                   className="w-16 bg-[var(--bg-card)] border border-[var(--border)] rounded p-1 text-[10px] font-black"
                                 />
                               </td>
                               <td className="p-4">
                                 <input 
                                   type="number"
                                   value={item.target}
                                   onChange={(e) => updateBudgetRow(idx, 'target', parseFloat(e.target.value) || 0)}
                                   className="w-16 bg-[var(--bg-card)] border border-[var(--border)] rounded p-1 text-[10px] font-black"
                                 />
                               </td>
                               <td className="p-4">
                                 <input 
                                   type="number"
                                   value={item.actual}
                                   onChange={(e) => updateBudgetRow(idx, 'actual', parseFloat(e.target.value) || 0)}
                                   className="w-16 bg-[var(--bg-card)] border border-[var(--border)] rounded p-1 text-[10px] font-black"
                                 />
                               </td>
                               <td className="p-4 text-[10px] font-bold">
                                 <span className={item.gap < 0 ? 'text-red-500' : item.gap > 0 ? 'text-amber-500' : 'text-green-500'}>
                                   {item.gap}
                                 </span>
                               </td>
                               <td className="p-4">
                                 <input 
                                   value={item.raised_by || ''}
                                   onChange={(e) => updateBudgetRow(idx, 'raised_by', e.target.value)}
                                   className="w-full bg-transparent border-none p-0 text-xs font-bold text-[var(--text-main)] focus:ring-0"
                                   placeholder="Name..."
                                 />
                               </td>
                               <td className="p-4">
                                 <input 
                                   value={item.raised_to || ''}
                                   onChange={(e) => updateBudgetRow(idx, 'raised_to', e.target.value)}
                                   className="w-full bg-transparent border-none p-0 text-xs font-bold text-[var(--text-main)] focus:ring-0"
                                   placeholder="Name..."
                                 />
                               </td>
                               <td className="p-4">
                                 <input 
                                   value={item.reason || ''}
                                   onChange={(e) => updateBudgetRow(idx, 'reason', e.target.value)}
                                   className="w-full bg-transparent border-none p-0 text-xs font-bold text-[var(--text-main)] focus:ring-0"
                                   placeholder="Reason..."
                                 />
                               </td>
                             </tr>
                           ))}
                         </tbody>
                       </table>
                     </div>
                   </div>

                   <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
                     <div className="space-y-1.5">
                       <label className="text-[10px] font-black uppercase text-[var(--text-muted)] ml-1">Verified Budget Adherence Score</label>
                       <input 
                         type="number"
                         value={achievement}
                         onChange={(e) => setAchievement(parseFloat(e.target.value) || 0)}
                         className="w-full bg-[var(--bg-card)] border border-[var(--border)] focus:border-purple-500 rounded-xl px-4 py-2 text-sm font-black text-[var(--text-main)] outline-none"
                         placeholder="Verified budget index score..."
                       />
                     </div>
                     <div className="space-y-1.5">
                       <label className="text-[10px] font-black uppercase text-[var(--text-muted)] ml-1">Budget Adherence Remarks</label>
                       <input 
                         value={remarks}
                         onChange={(e) => setRemarks(e.target.value)}
                         className="w-full bg-[var(--bg-card)] border border-[var(--border)] focus:border-purple-500 rounded-xl px-4 py-2 text-xs font-bold text-[var(--text-main)] outline-none"
                         placeholder="Provide overall budget feedback..."
                       />
                     </div>
                   </div>
                 </div>
               ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="space-y-4 bg-[var(--input-bg)]/30 p-5 rounded-2xl border border-[var(--border)]">
                    <h3 className="text-xs font-black uppercase text-blue-500 tracking-wider">Doer Submission Data</h3>
                    
                    <div className="grid grid-cols-2 gap-4">
                      <div className="bg-[var(--bg-card)] p-4 rounded-xl border border-[var(--border)]">
                        <span className="text-[10px] font-black uppercase text-[var(--text-muted)] block">Target</span>
                        <span className="text-lg font-black text-[var(--text-main)]">{subsection.target} {subsection.isPercentage ? '%' : ''}</span>
                      </div>
                      <div className="bg-[var(--bg-card)] p-4 rounded-xl border border-[var(--border)]">
                        <span className="text-[10px] font-black uppercase text-[var(--text-muted)] block">Reported Achievement</span>
                        <span className="text-lg font-black text-amber-500">{subsection.achievement} {subsection.isPercentage ? '%' : ''}</span>
                      </div>
                    </div>

                    <div className="space-y-1">
                      <label className="text-[10px] font-black uppercase text-[var(--text-muted)] ml-1">Subsection Weightage</label>
                      <div className="bg-[var(--bg-card)] px-4 py-2.5 rounded-xl border border-[var(--border)] font-black text-xs text-blue-500">
                        {subsection.weightage}% of Parameter Weight
                      </div>
                    </div>
                  </div>

                  <div className="space-y-4 bg-amber-500/5 p-5 rounded-2xl border border-amber-500/10">
                    <h3 className="text-xs font-black uppercase text-amber-600 tracking-wider">Auditor Verification</h3>
                    
                    <div className="space-y-1.5">
                      <label className="text-[10px] font-black uppercase text-[var(--text-muted)] ml-1">Audited Achievement Score</label>
                      <div className="relative">
                        <input 
                          type="number"
                          value={achievement}
                          onChange={(e) => setAchievement(parseFloat(e.target.value) || 0)}
                          className="w-full bg-[var(--bg-card)] border border-[var(--border)] focus:border-amber-500 rounded-xl px-4 py-2.5 text-sm font-black text-[var(--text-main)] outline-none transition-all"
                          placeholder="Enter verified achievement..."
                        />
                        {subsection.isPercentage && (
                          <span className="absolute right-4 top-1/2 -translate-y-1/2 text-xs font-black text-blue-500 uppercase">%</span>
                        )}
                      </div>
                    </div>

                    <div className="space-y-1.5">
                      <label className="text-[10px] font-black uppercase text-[var(--text-muted)] ml-1">Verification Remarks / Comments</label>
                      <textarea 
                        value={remarks}
                        onChange={(e) => setRemarks(e.target.value)}
                        className="w-full bg-[var(--bg-card)] border border-[var(--border)] focus:border-amber-500 rounded-xl px-4 py-2 text-xs font-bold text-[var(--text-main)] outline-none min-h-[100px] transition-all resize-none"
                        placeholder="Enter audit remarks, evidence verification notes, etc..."
                      />
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div className="p-6 border-t border-[var(--border)] bg-[var(--input-bg)]/30 flex justify-between items-center">
              {isProcessScore ? (
                <>
                  <div className="flex flex-col">
                    <span className="text-[10px] font-black uppercase text-[var(--text-muted)]">Total Obtained Marks</span>
                    <span className="text-2xl font-black text-blue-500">{totalObtained}</span>
                  </div>
                  <button 
                    onClick={() => onSave(checklist, unitName, totalObtained)}
                    className="px-10 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-2xl font-black text-xs uppercase tracking-widest shadow-xl shadow-blue-500/30 transition-all active:scale-95 flex items-center gap-2"
                  >
                    <Save size={16} /> Update Matrix Achievement
                  </button>
                </>
              ) : isNpsOrCsi ? (
                <>
                  <div className="flex flex-col">
                    <span className="text-[10px] font-black uppercase text-[var(--text-muted)]">Audited Score Preview</span>
                    <span className="text-lg font-black text-blue-500">
                      {achievement} {subsection.isPercentage ? '%' : ''} (MM: {subsection.weightage}%)
                    </span>
                  </div>
                  <button 
                    onClick={() => onSave(null, unitName, achievement, remarks, googleSheetLink, googleFormLink)}
                    className="px-10 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-2xl font-black text-xs uppercase tracking-widest shadow-xl shadow-blue-500/30 transition-all active:scale-95 flex items-center gap-2"
                  >
                    <Save size={16} /> Update Matrix Achievement
                  </button>
                </>
              ) : isTeamEngagement ? (
                <>
                  <div className="flex flex-col">
                    <span className="text-[10px] font-black uppercase text-[var(--text-muted)]">Audited Score Preview</span>
                    <span className="text-lg font-black text-blue-500">
                      {achievement} {subsection.isPercentage ? '%' : ''} (MM: {subsection.weightage}%)
                    </span>
                  </div>
                  <button 
                    onClick={() => onSave(null, unitName, achievement, remarks, googleSheetLink, googleFormLink, teamChecklist, surveyDoerName, surveyDoerEmail)}
                    className="px-10 py-3 bg-purple-600 hover:bg-purple-700 text-white rounded-2xl font-black text-xs uppercase tracking-widest shadow-xl shadow-purple-500/30 transition-all active:scale-95 flex items-center gap-2"
                  >
                    <Save size={16} /> Update Matrix Achievement
                  </button>
                </>
              ) : isBudgetAdherence ? (
                <>
                  <div className="flex flex-col">
                    <span className="text-[10px] font-black uppercase text-[var(--text-muted)]">Audited Score Preview</span>
                    <span className="text-lg font-black text-blue-500">
                      {achievement} {subsection.isPercentage ? '%' : ''} (MM: {subsection.weightage}%)
                    </span>
                  </div>
                  <button 
                    onClick={() => onSave(null, unitName, achievement, remarks, null, null, null, null, null, budgetChecklist)}
                    className="px-10 py-3 bg-purple-600 hover:bg-purple-700 text-white rounded-2xl font-black text-xs uppercase tracking-widest shadow-xl shadow-purple-500/30 transition-all active:scale-95 flex items-center gap-2"
                  >
                    <Save size={16} /> Update Matrix Achievement
                  </button>
                </>
              ) : (
                <>
                  <div className="flex flex-col">
                    <span className="text-[10px] font-black uppercase text-[var(--text-muted)]">Audited Score Preview</span>
                    <span className="text-lg font-black text-blue-500">
                      {achievement} {subsection.isPercentage ? '%' : ''} (MM: {subsection.weightage}%)
                    </span>
                  </div>
                  <button 
                    onClick={() => onSave(null, unitName, achievement, remarks)}
                    className="px-10 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-2xl font-black text-xs uppercase tracking-widest shadow-xl shadow-blue-500/30 transition-all active:scale-95 flex items-center gap-2"
                  >
                    <Save size={16} /> Update Matrix Achievement
                  </button>
                </>
              )}
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};

const RequestChangeModal = ({ isOpen, onClose, parameters, period, onSubmitted }) => {
  const { showSuccess, showError } = useNotification();

  const options = [];
  (parameters || []).forEach(p =>
    (p.subsections || []).forEach(s =>
      options.push({ paramId: p.id, paramName: p.name, subId: s.id, subName: s.name, target: s.target, achievement: s.achievement })
    )
  );

  const [selKey, setSelKey] = useState(options[0] ? `${options[0].paramId}::${options[0].subId}` : '');
  const [field, setField] = useState('target');
  const [value, setValue] = useState('');
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);

  const sel = options.find(o => `${o.paramId}::${o.subId}` === selKey);
  const currentValue = sel ? (field === 'target' ? sel.target : sel.achievement) : '';

  const submit = async () => {
    if (!sel) { showError('Select a subsection'); return; }
    if (value === '' || Number.isNaN(parseFloat(value))) { showError('Enter a valid new value'); return; }
    if (!reason.trim()) { showError('Please provide a reason for the change'); return; }
    setSaving(true);
    try {
      await api.post('/orm-target-requests', {
        period,
        reason: reason.trim(),
        changes: [{
          parameter_id: sel.paramId,
          subsection_id: sel.subId,
          parameter_name: sel.paramName,
          subsection_name: sel.subName,
          field,
          current_value: parseFloat(currentValue) || 0,
          requested_value: parseFloat(value),
        }],
      });
      showSuccess('Target change request submitted for staff approval');
      onSubmitted && onSubmitted();
      onClose();
    } catch (e) {
      showError(e.response?.data?.detail || 'Failed to submit request');
    } finally {
      setSaving(false);
    }
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
          <motion.div initial={{ scale: 0.9, opacity: 0, y: 20 }} animate={{ scale: 1, opacity: 1, y: 0 }} exit={{ scale: 0.9, opacity: 0, y: 20 }} className="relative w-full max-w-lg bg-[var(--bg-card)] rounded-[28px] border border-[var(--border)] shadow-2xl overflow-hidden">
            <div className="p-6 border-b border-[var(--border)] bg-[var(--input-bg)]/30 flex justify-between items-center">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-amber-500/10 rounded-xl text-amber-600"><Send size={20} /></div>
                <div>
                  <h2 className="text-lg font-black text-[var(--text-main)]">Request Target Change</h2>
                  <p className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">Window closed · sent to staff for approval</p>
                </div>
              </div>
              <button onClick={onClose} className="p-2 hover:bg-red-500/10 text-red-500 rounded-xl transition-all"><X size={18} /></button>
            </div>

            <div className="p-6 space-y-4">
              {options.length === 0 ? (
                <p className="text-xs font-bold text-[var(--text-muted)] text-center py-6">No subsections available to request changes for.</p>
              ) : (
                <>
                  <div className="space-y-1">
                    <label className="text-[10px] font-black uppercase text-[var(--text-muted)]">Subsection</label>
                    <select value={selKey} onChange={e => setSelKey(e.target.value)} className="w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-xl px-3 py-2 text-xs font-bold text-[var(--text-main)] outline-none focus:border-amber-500">
                      {options.map(o => <option key={`${o.paramId}::${o.subId}`} value={`${o.paramId}::${o.subId}`}>{o.paramName} — {o.subName}</option>)}
                    </select>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1">
                      <label className="text-[10px] font-black uppercase text-[var(--text-muted)]">Field</label>
                      <select value={field} onChange={e => setField(e.target.value)} className="w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-xl px-3 py-2 text-xs font-bold text-[var(--text-main)] outline-none focus:border-amber-500">
                        <option value="target">Target</option>
                        <option value="achievement">Achievement</option>
                      </select>
                    </div>
                    <div className="space-y-1">
                      <label className="text-[10px] font-black uppercase text-[var(--text-muted)]">New Value</label>
                      <input type="number" value={value} onChange={e => setValue(e.target.value)} placeholder={`Current: ${currentValue ?? 0}`} className="w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-xl px-3 py-2 text-xs font-black text-[var(--text-main)] outline-none focus:border-amber-500" />
                    </div>
                  </div>
                  <div className="space-y-1">
                    <label className="text-[10px] font-black uppercase text-[var(--text-muted)]">Reason</label>
                    <textarea value={reason} onChange={e => setReason(e.target.value)} rows={3} placeholder="Explain why this change is needed outside the target window..." className="w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-xl px-3 py-2 text-xs font-bold text-[var(--text-main)] outline-none focus:border-amber-500 resize-none" />
                  </div>
                </>
              )}
            </div>

            <div className="p-6 border-t border-[var(--border)] bg-[var(--input-bg)]/30 flex justify-end gap-3">
              <button onClick={onClose} className="px-6 py-2.5 bg-[var(--input-bg)] border border-[var(--border)] text-[var(--text-muted)] rounded-xl text-xs font-black uppercase">Cancel</button>
              <button onClick={submit} disabled={saving || options.length === 0} className="px-8 py-2.5 bg-amber-600 hover:bg-amber-700 text-white rounded-xl text-xs font-black uppercase tracking-widest shadow-lg shadow-amber-500/20 flex items-center gap-2 disabled:opacity-50">
                <Send size={14} /> {saving ? 'Submitting...' : 'Submit Request'}
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};

const ORMDesigner = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();
  const [availableUsers, setAvailableUsers] = useState([]);
  const [loadingUsers, setLoadingUsers] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [activeAudit, setActiveAudit] = useState(null);
  const [showRequestModal, setShowRequestModal] = useState(false);
  const [pendingRequests, setPendingRequests] = useState([]);
  // Target window (25th → 10th). Seeded client-side, refreshed from the API which
  // is the enforcing source of truth.
  const [windowOpen, setWindowOpen] = useState(() => {
    const d = new Date().getDate();
    return d >= 25 || d <= 10;
  });

  // Month selector: lets admins view past months (read-only) or edit the current month.
  const monthOptions = React.useMemo(() => {
    const opts = [];
    const now = new Date();
    for (let i = 0; i < 12; i++) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
      const label = d.toLocaleString('default', { month: 'long', year: 'numeric' });
      opts.push({ value, label });
    }
    return opts;
  }, []);
  const currentPeriod = monthOptions[0]?.value;
  const [selectedPeriod, setSelectedPeriod] = useState(currentPeriod);
  const isCurrentPeriod = selectedPeriod === currentPeriod;

  useEffect(() => {
    const fetchUsers = async () => {
      try {
        const response = await api.get('/users?active_only=true');
        setAvailableUsers(response.data);
      } catch (error) {
        console.error('Error fetching users:', error);
      } finally {
        setLoadingUsers(false);
      }
    };
    fetchUsers();
  }, []);

  const [parameters, setParameters] = useState([]);

  useEffect(() => {
    const fetchORM = async () => {
      if (!user?.company_id || !selectedPeriod) return;
      setIsLoading(true);
      try {
        const response = await api.get(`/orm/${user.company_id}`, { params: { period: selectedPeriod } });
        if (typeof response.data.target_window_open === 'boolean') {
          setWindowOpen(response.data.target_window_open);
        }
        if (response.data.parameters && response.data.parameters.length > 0) {
          setParameters(response.data.parameters);
        } else {
          setParameters(defaultTemplate);
        }
      } catch (error) {
        console.error('Error fetching ORM:', error);
        setParameters(defaultTemplate);
      } finally {
        setIsLoading(false);
      }
    };
    fetchORM();
  }, [user?.company_id, selectedPeriod]);

  const defaultTemplate = [
    {
      id: 'p1', name: 'Revenue Target vs Achi', weightage: 30, assignedUsers: [],
      subsections: [
        { id: 's1', name: 'Location A', weightage: 6, target: 50000, achievement: 50000, assignedUsers: [] },
      ]
    },
    {
      id: 'p2', name: 'Process score', weightage: 16, assignedUsers: [],
      subsections: [
        { id: 's6', name: 'Service', weightage: 4, target: 25, achievement: 24, isPercentage: true, assignedUsers: [] },
      ]
    }
  ];

  const [expandedParams, setExpandedParams] = useState(['p1', 'p2', 'p3', 'p4', 'p5']);

  const toggleExpand = (id) => {
    setExpandedParams(prev => prev.includes(id) ? prev.filter(p => p !== id) : [...prev, id]);
  };

  const calculateScore = (sub, isReverse) => {
    if (!sub.target || sub.target === 0) return 0;
    let score;
    if (isReverse) {
      score = (sub.target / sub.achievement) * sub.weightage;
    } else {
      score = (sub.achievement / sub.target) * sub.weightage;
    }
    return Math.min(score, sub.weightage).toFixed(2);
  };

  const updateParameter = (pId, field, value) => {
    setParameters(prev => prev.map(p => p.id === pId ? { ...p, [field]: value } : p));
  };

  const updateSubsection = (pId, sId, field, value) => {
    setParameters(prev => prev.map(p => {
      if (p.id === pId) {
        const newSubsections = p.subsections.map(s => 
          s.id === sId ? { ...s, [field]: value } : s
        );
        const totalWeight = newSubsections.reduce((acc, s) => acc + (parseFloat(s.weightage) || 0), 0);
        return { ...p, subsections: newSubsections, weightage: totalWeight };
      }
      return p;
    }));
  };

  const isAdmin = ['superadmin', 'admin', 'clientadmin'].includes(user?.role);
  const isStaff = ['superadmin', 'admin'].includes(user?.role);
  // Client admins can only edit targets/achievements while the window is open.
  // Staff bypass it (they handle exceptions via the approval flow).
  const windowLocked = !isStaff && !windowOpen;

  // Client admins: surface how many of their target-change requests are still pending.
  useEffect(() => {
    if (!user || isStaff) return;
    api.get('/orm-target-requests', { params: { status_filter: 'pending' } })
      .then(r => setPendingRequests(r.data.requests || []))
      .catch(() => {});
  }, [user?._id, isStaff, showRequestModal]);

  const canEdit = (assignedUserIds) => {
    if (!user) return false;
    if (isAdmin) return true;
    return assignedUserIds?.includes(user._id);
  };

  const visibleParameters = parameters.filter(p => {
    if (isAdmin) return true;
    const hasParamAccess = p.assignedUsers?.includes(user?._id);
    const hasSubAccess = p.subsections.some(s => s.assignedUsers?.includes(user?._id));
    return hasParamAccess || hasSubAccess;
  });

  const totalWeightage = visibleParameters.reduce((acc, p) => {
    if (isAdmin) return acc + (parseFloat(p.weightage) || 0);
    const subWeight = p.subsections.filter(s => s.assignedUsers?.includes(user?._id)).reduce((sAcc, s) => sAcc + (parseFloat(s.weightage) || 0), 0);
    return acc + subWeight;
  }, 0);

  const totalScore = visibleParameters.reduce((acc, p) => {
    const pScore = p.subsections.filter(s => isAdmin || s.assignedUsers?.includes(user?._id)).reduce((sAcc, s) => sAcc + parseFloat(calculateScore(s, p.isReverse)), 0);
    return acc + pScore;
  }, 0);

  const handleSave = async () => {
    if (!isCurrentPeriod) {
      showError('Past months are read-only. Switch to the current month to make changes.');
      return;
    }
    if (windowLocked) {
      showError('Target window is closed (opens 25th–10th). Submit a change request for staff approval.');
      return;
    }
    setIsSaving(true);
    try {
      await api.post('/orm', {
        company_id: user.company_id,
        parameters: sanitizeORMParameters(parameters),
        total_weightage: totalWeightage,
        total_score: totalScore,
        period: selectedPeriod
      });
      showSuccess('ORM configuration saved successfully');
    } catch (error) {
      showError(error.response?.data?.detail || 'Failed to save ORM');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDownloadPDF = () => {
    const formatVal = (v, sub) => {
      const n = parseFloat(v);
      if (!Number.isFinite(n)) return '';
      return sub?.isPercentage ? `${n}%` : `${n.toLocaleString()}`;
    };

    const doc = new jsPDF({ orientation: 'portrait', unit: 'pt', format: 'a4' });
    const pageWidth = doc.internal.pageSize.getWidth();

    doc.setFont('helvetica', 'bold');
    doc.setFontSize(14);
    doc.text('ORGANIZATION RESULT MATRIX (ORM) format', pageWidth / 2, 36, { align: 'center' });

    const body = [];
    let grandWeight = 0;
    let grandScore = 0;

    visibleParameters.forEach(param => {
      const subs = isAdmin
        ? param.subsections
        : param.subsections.filter(s => s.assignedUsers?.includes(user?._id));

      let paramWeight = 0;
      let paramScore = 0;

      subs.forEach(sub => {
        const score = parseFloat(calculateScore(sub, param.isReverse)) || 0;
        paramWeight += parseFloat(sub.weightage) || 0;
        paramScore += score;
        body.push([
          param.name,
          sub.name,
          (parseFloat(sub.weightage) || 0).toFixed(1),
          formatVal(sub.target, sub),
          formatVal(sub.achievement, sub),
          score.toFixed(2)
        ]);
      });

      grandWeight += paramWeight;
      grandScore += paramScore;

      body.push([
        { content: `${param.name} Total`, styles: { fontStyle: 'bold', fillColor: [232, 244, 232] } },
        { content: '', styles: { fillColor: [232, 244, 232] } },
        { content: paramWeight.toFixed(1), styles: { fontStyle: 'bold', fillColor: [232, 244, 232] } },
        { content: '', styles: { fillColor: [232, 244, 232] } },
        { content: '', styles: { fillColor: [232, 244, 232] } },
        { content: paramScore.toFixed(2), styles: { fontStyle: 'bold', fillColor: [232, 244, 232] } }
      ]);
    });

    body.push([
      { content: 'Grand Total', styles: { fontStyle: 'bold', fillColor: [208, 230, 208] } },
      { content: '', styles: { fillColor: [208, 230, 208] } },
      { content: grandWeight.toFixed(1), styles: { fontStyle: 'bold', fillColor: [208, 230, 208] } },
      { content: '', styles: { fillColor: [208, 230, 208] } },
      { content: '', styles: { fillColor: [208, 230, 208] } },
      { content: grandScore.toFixed(2), styles: { fontStyle: 'bold', fillColor: [208, 230, 208] } }
    ]);

    autoTable(doc, {
      startY: 56,
      head: [['Five-Parameters', 'Subs', 'Weightage', 'Target', 'Achievement', 'Score']],
      body,
      theme: 'grid',
      styles: { fontSize: 9, cellPadding: 4, lineColor: [180, 200, 180], lineWidth: 0.5, textColor: [40, 40, 40] },
      headStyles: { fillColor: [208, 230, 208], textColor: [20, 20, 20], fontStyle: 'bold' },
      columnStyles: {
        0: { cellWidth: 110 },
        1: { cellWidth: 90 },
        2: { cellWidth: 60, halign: 'center' },
        3: { cellWidth: 70, halign: 'right' },
        4: { cellWidth: 75, halign: 'right' },
        5: { cellWidth: 50, halign: 'center' }
      }
    });

    const today = new Date().toISOString().slice(0, 10);
    doc.save(`ORM_Performance_Matrix_${today}.pdf`);
  };

  if (isLoading) return null;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-8 bg-[var(--bg-main)] min-h-screen">
      {/* Header Section */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-[var(--border)] pb-6">
        <div>
          <h1 className="text-3xl font-black text-[var(--text-main)] flex items-center gap-3">
            <Layers className="text-blue-500" />
            Organization Result Matrix (ORM)
          </h1>
          <p className="text-[var(--text-muted)] mt-1 font-bold">Monitor and update your ORM achievement scores</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-2 rounded-2xl border border-[var(--border)] bg-[var(--bg-card)]">
            <Calendar size={16} className="text-blue-500" />
            <select
              value={selectedPeriod}
              onChange={(e) => setSelectedPeriod(e.target.value)}
              className="bg-transparent text-xs font-black uppercase tracking-tighter text-[var(--text-main)] outline-none cursor-pointer"
            >
              {monthOptions.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
          {!isCurrentPeriod && (
            <div className="flex items-center gap-2 px-4 py-2 rounded-full border bg-amber-500/10 border-amber-500/20 text-amber-600">
              <Info size={14} />
              <span className="text-[10px] font-black uppercase tracking-tighter">Read-only history</span>
            </div>
          )}
          <div className={`flex items-center gap-2 px-4 py-2 rounded-full border ${totalWeightage === 100 ? 'bg-green-500/10 border-green-500/20 text-green-500' : 'bg-orange-500/10 border-orange-500/20 text-orange-500'}`}>
            <span className="text-sm font-black uppercase tracking-tighter">Allocation: {totalWeightage}%</span>
          </div>
          {isAdmin && isCurrentPeriod && (
            <button 
              onClick={() => navigate('/orm/setup')}
              className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-2xl transition-all shadow-xl shadow-blue-500/20 font-black text-xs uppercase tracking-widest"
            >
              <Settings2 size={16} /> Setup Matrix
            </button>
          )}
          <button
            onClick={handleDownloadPDF}
            className="flex items-center gap-2 px-5 py-2.5 bg-[var(--bg-card)] border border-[var(--border)] hover:border-blue-500/50 text-[var(--text-main)] rounded-2xl transition-all font-black text-xs uppercase tracking-widest shadow-lg"
          >
            <FileText size={16} /> Download PDF
          </button>
          {isCurrentPeriod && !windowLocked && (
            <button
              onClick={handleSave}
              disabled={isSaving}
              className={`flex items-center gap-2 px-5 py-2.5 bg-[var(--bg-card)] border border-[var(--border)] hover:border-blue-500/50 text-[var(--text-main)] rounded-2xl transition-all font-black text-xs uppercase tracking-widest shadow-lg ${isSaving ? 'opacity-50 cursor-wait' : ''}`}
            >
              <Save size={16} className={isSaving ? 'animate-pulse' : ''} />
              {isSaving ? 'Syncing...' : 'Save Matrix'}
            </button>
          )}
          {isCurrentPeriod && windowLocked && (
            <button
              onClick={() => setShowRequestModal(true)}
              className="flex items-center gap-2 px-5 py-2.5 bg-amber-600 hover:bg-amber-700 text-white rounded-2xl transition-all font-black text-xs uppercase tracking-widest shadow-lg shadow-amber-500/20"
            >
              <Send size={16} /> Request Change
            </button>
          )}
        </div>
      </div>

      {/* Target window banner (client admins, current month, window closed) */}
      {isCurrentPeriod && windowLocked && (
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-amber-500/10 border border-amber-500/20 rounded-2xl px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-amber-500/15 rounded-xl text-amber-600"><Lock size={18} /></div>
            <div>
              <p className="text-xs font-black uppercase tracking-wider text-amber-700">Target window is closed</p>
              <p className="text-[11px] font-bold text-[var(--text-muted)]">
                Targets & achievements can be edited from the 25th to the 10th of each month. For exceptions, submit a change request for staff approval.
                {pendingRequests.length > 0 && (
                  <span className="ml-1 text-amber-700">You have {pendingRequests.length} pending request{pendingRequests.length > 1 ? 's' : ''}.</span>
                )}
              </p>
            </div>
          </div>
          <button
            onClick={() => setShowRequestModal(true)}
            className="shrink-0 flex items-center gap-2 px-4 py-2 bg-amber-600 hover:bg-amber-700 text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-lg shadow-amber-500/20"
          >
            <Send size={14} /> Request Target Change
          </button>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="bg-[var(--bg-card)] p-5 rounded-[24px] border border-[var(--border)] shadow-sm">
          <div className="flex items-center gap-3 mb-3">
            <div className="p-2 bg-blue-500/10 rounded-xl text-blue-500"><Calculator size={20} /></div>
            <span className="text-[var(--text-muted)] text-[10px] font-black uppercase tracking-widest">Aggregate Score</span>
          </div>
          <div className="text-3xl font-black text-[var(--text-main)] tracking-tighter">{totalScore.toFixed(2)} / 100</div>
          <div className="mt-3 h-2 bg-[var(--input-bg)] rounded-full overflow-hidden">
            <motion.div initial={{ width: 0 }} animate={{ width: `${totalScore}%` }} className="h-full bg-blue-500" />
          </div>
        </div>
        {/* Other cards can be simplified or removed for focus */}
      </div>

      {/* Matrix Table Area */}
      <div className="space-y-4">
        {visibleParameters.map((param) => (
          <div key={param.id} className="bg-[var(--bg-card)] rounded-[24px] border border-[var(--border)] overflow-hidden shadow-sm">
            <div className="p-4 flex items-center justify-between bg-[var(--input-bg)]/20 border-b border-[var(--border)]">
              <div className="flex items-center gap-3">
                <button onClick={() => toggleExpand(param.id)} className="p-1 hover:bg-[var(--input-bg)] rounded-lg transition-colors">
                  {expandedParams.includes(param.id) ? <ChevronDown size={20} /> : <ChevronRight size={20} />}
                </button>
                <h3 className="text-lg font-black text-[var(--text-main)]">{param.name}</h3>
                <span className={`px-2 py-0.5 rounded text-[9px] font-black uppercase border ${param.isReverse ? 'bg-orange-500/10 text-orange-500 border-orange-500/20' : 'bg-blue-500/10 text-blue-500 border-blue-500/20'}`}>
                    {param.isReverse ? 'Reverse Logic' : 'Standard Logic'}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-black uppercase text-[var(--text-muted)]">Param Weight:</span>
                <span className="text-sm font-black text-blue-500">{param.weightage}%</span>
              </div>
            </div>

            <AnimatePresence>
              {expandedParams.includes(param.id) && (
                <motion.div initial={{ height: 0 }} animate={{ height: 'auto' }} exit={{ height: 0 }} className="overflow-hidden">
                  <div className="p-4 overflow-x-auto">
                    <table className="w-full text-left border-collapse">
                      <thead>
                        <tr className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] border-b border-[var(--border)]">
                          <th className="pb-3 px-4">Sub-Section Name</th>
                          <th className="pb-3 px-4">Weight</th>
                          <th className="pb-3 px-4">Target</th>
                          <th className="pb-3 px-4">Achievement</th>
                          <th className="pb-3 px-4">Performance Score</th>
                          <th className="pb-3 px-4">Reminders</th>
                        </tr>
                      </thead>
                      <tbody>
                        {param.subsections.filter(sub => isAdmin || sub.assignedUsers?.includes(user?._id)).map((sub) => (
                          <tr key={sub.id} className="group border-b border-[var(--border)]/50 last:border-0 hover:bg-white/5 transition-colors">
                            <td className="py-4 px-4">
                                <div className="flex items-center gap-2">
                                    <span className="text-xs font-black text-[var(--text-main)]">{sub.name}</span>
                                    {sub.hasAudit && isCurrentPeriod && !windowLocked && (
                                        <button
                                            onClick={() => setActiveAudit({ paramId: param.id, sub })}
                                            className="inline-flex items-center gap-1.5 px-2 py-1 bg-amber-500 text-white rounded-lg text-[9px] font-black uppercase shadow-lg shadow-amber-500/20 hover:scale-105 transition-all"
                                        >
                                            <ClipboardCheck size={10} /> Perform Audit
                                        </button>
                                    )}
                                </div>
                                {sub.unitName && <p className="text-[9px] font-bold text-[var(--text-muted)] mt-1 uppercase">Unit: {sub.unitName}</p>}
                            </td>
                            <td className="py-4 px-4 text-xs font-black text-blue-500">{sub.weightage}%</td>
                            <td className="py-4 px-4">
                                <input
                                    type="number" value={sub.target}
                                    disabled={!isAdmin || !isCurrentPeriod || windowLocked}
                                    onChange={(e) => updateSubsection(param.id, sub.id, 'target', e.target.value)}
                                    className="w-20 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl px-2 py-1 text-xs font-black outline-none focus:border-blue-500 disabled:opacity-50"
                                />
                            </td>
                            <td className="py-4 px-4">
                                <div className="flex items-center gap-2">
                                    <input
                                        type="number" value={sub.achievement}
                                        disabled={param.id === 'p1' || !canEdit(sub.assignedUsers) || sub.hasAudit || !isCurrentPeriod || windowLocked}
                                        onChange={(e) => updateSubsection(param.id, sub.id, 'achievement', e.target.value)}
                                        className={`w-20 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl px-2 py-1 text-xs font-black outline-none focus:border-blue-500 ${(param.id === 'p1' || sub.hasAudit) ? 'opacity-50 cursor-not-allowed text-amber-600 border-amber-500/30' : ''} disabled:opacity-50`}
                                    />
                                    {sub.isPercentage && <span className="text-blue-500 text-[10px] font-black uppercase">Pct</span>}
                                </div>
                            </td>
                            <td className="py-4 px-4">
                                <div className="flex items-center gap-2 font-black text-xs">
                                    <span className={parseFloat(calculateScore(sub, param.isReverse)) >= sub.weightage * 0.7 ? 'text-green-500' : 'text-orange-500'}>
                                        {calculateScore(sub, param.isReverse)}
                                    </span>
                                    {parseFloat(calculateScore(sub, param.isReverse)) >= sub.weightage * 0.9 ? <TrendingUp size={14} className="text-green-500" /> : <TrendingDown size={14} className="text-orange-500" />}
                                </div>
                            </td>
                            <td className="py-4 px-4">
                                <div className="flex flex-col gap-0.5">
                                    <span className="text-[10px] font-black text-blue-500 uppercase">{sub.frequency || 'None'}</span>
                                    {sub.frequency && sub.frequency !== 'none' && <span className="text-[9px] font-bold text-[var(--text-muted)]">Day {sub.dayOfMonth}</span>}
                                </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        ))}
      </div>

      <RequestChangeModal
        key={`req-${selectedPeriod}-${showRequestModal}`}
        isOpen={showRequestModal}
        onClose={() => setShowRequestModal(false)}
        parameters={visibleParameters}
        period={selectedPeriod}
        onSubmitted={() => {}}
      />

      {activeAudit && (
        <AuditModal
            isOpen={!!activeAudit}
            onClose={() => setActiveAudit(null)}
            subsection={activeAudit.sub}
            paramId={activeAudit.paramId}
            paramName={parameters.find(p => p.id === activeAudit.paramId)?.name}
            onSave={(checklist, unitName, achievement, remarks, googleSheetLink, googleFormLink, teamChecklist, doerName, doerEmail, budgetChecklist) => {
                if (checklist) {
                  updateSubsection(activeAudit.paramId, activeAudit.sub.id, 'auditChecklist', checklist);
                }
                updateSubsection(activeAudit.paramId, activeAudit.sub.id, 'unitName', unitName);
                updateSubsection(activeAudit.paramId, activeAudit.sub.id, 'achievement', achievement);
                if (remarks !== undefined) {
                  updateSubsection(activeAudit.paramId, activeAudit.sub.id, 'remarks', remarks);
                }
                if (googleSheetLink !== undefined) {
                  updateSubsection(activeAudit.paramId, activeAudit.sub.id, 'googleSheetLink', googleSheetLink);
                }
                if (googleFormLink !== undefined) {
                  updateSubsection(activeAudit.paramId, activeAudit.sub.id, 'googleFormLink', googleFormLink);
                }
                if (teamChecklist !== undefined) {
                  updateSubsection(activeAudit.paramId, activeAudit.sub.id, 'teamEngagementChecklist', teamChecklist);
                }
                if (doerName !== undefined) {
                  updateSubsection(activeAudit.paramId, activeAudit.sub.id, 'surveyDoerName', doerName);
                }
                if (doerEmail !== undefined) {
                  updateSubsection(activeAudit.paramId, activeAudit.sub.id, 'surveyDoerEmail', doerEmail);
                }
                if (budgetChecklist !== undefined) {
                  updateSubsection(activeAudit.paramId, activeAudit.sub.id, 'budgetAdherenceChecklist', budgetChecklist);
                }
                setActiveAudit(null);
                showSuccess('Audit scores synchronized with Matrix');
            }}
        />
      )}

      <style dangerouslySetInnerHTML={{ __html: `
        .custom-scrollbar::-webkit-scrollbar { width: 5px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: var(--border); border-radius: 10px; }
      `}} />
    </div>
  );
};

export default ORMDesigner;
