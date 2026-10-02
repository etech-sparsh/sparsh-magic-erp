import React, { useState, useEffect, useRef, useLayoutEffect } from 'react';
import { createPortal } from 'react-dom';
import {  AnimatePresence , motion } from 'framer-motion';
import { 
  Plus, Trash2, Save, ChevronDown, ChevronRight, 
  Target, BarChart3, PieChart, Info, AlertCircle, CheckCircle2,
  TrendingUp, TrendingDown, Layers, Calculator, Users, UserPlus, X,
  Calendar, Clock, BellRing, ArrowRight, ArrowLeft, Settings2,
  Lock, Globe, ShieldCheck, ClipboardCheck, FileDown, FileUp
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import api from '../../services/api';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import * as XLSX from 'xlsx';
import { sanitizeORMParameters } from '../../utils/ormSanitize';

const ORMSetup = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { showSuccess, showError } = useNotification();
  const [availableUsers, setAvailableUsers] = useState([]);
  const [loadingUsers, setLoadingUsers] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [currentStep, setCurrentStep] = useState(1);
  const [activeParamIndex, setActiveParamIndex] = useState(0);

  const [parameters, setParameters] = useState([]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [usersRes, ormRes] = await Promise.all([
          api.get(`/users?active_only=true&company_id=${user.company_id}`),
          api.get(`/orm/${user.company_id}`)
        ]);
        
        setAvailableUsers(usersRes.data);
        
        if (ormRes.data.parameters && ormRes.data.parameters.length > 0) {
          setParameters(ormRes.data.parameters);
        } else {
          setParameters(defaultTemplate);
        }
      } catch (error) {
        console.error('Error fetching data:', error);
        setParameters(defaultTemplate);
      } finally {
        setIsLoading(false);
        setLoadingUsers(false);
      }
    };
    if (user?.company_id) fetchData();
  }, [user?.company_id]);

  const defaultTemplate = [
    { id: 'p1', name: 'Revenue Target vs Achi', weightage: 30, assignedUsers: [], subsections: [] },
    { id: 'p2', name: 'Process score', weightage: 16, assignedUsers: [], subsections: [] },
    { id: 'p3', name: 'NPS OR CSI', weightage: 20, assignedUsers: [], subsections: [] },
    { id: 'p4', name: 'Team Engagement index', weightage: 15, assignedUsers: [], subsections: [] },
    { id: 'p5', name: 'Budget Cost Adherence', weightage: 19, isReverse: true, assignedUsers: [], subsections: [] }
  ];

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

  const addSubsection = (pId) => {
    setParameters(prev => prev.map(p => {
      if (p.id === pId) {
        return {
          ...p,
          subsections: [
            ...p.subsections,
            { id: `s${Date.now()}`, name: 'New Subsection', weightage: 0, target: 0, achievement: 0, assignedUsers: [], frequency: 'none', dayOfMonth: 1, isPercentage: false, hasAudit: false, auditName: '', unitName: '', auditChecklist: [] }
          ]
        };
      }
      return p;
    }));
  };

  const removeSubsection = (pId, sId) => {
    setParameters(prev => prev.map(p => {
      if (p.id === pId) {
        const newSubs = p.subsections.filter(s => s.id !== sId);
        const totalWeight = newSubs.reduce((acc, s) => acc + (parseFloat(s.weightage) || 0), 0);
        return { ...p, subsections: newSubs, weightage: totalWeight };
      }
      return p;
    }));
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

  const addAuditRow = (pId, sId) => {
    setParameters(prev => prev.map(p => {
      if (p.id === pId) {
        return {
          ...p,
          subsections: p.subsections.map(s => {
            if (s.id === sId) {
              const nextSno = (s.auditChecklist?.length || 0) + 1;
              return {
                ...s,
                auditChecklist: [
                  ...(s.auditChecklist || []),
                  { sno: nextSno, checkpoint: '', max_marks: 5.0, response: 'No', obtained_marks: 0.0, remarks: '' }
                ]
              };
            }
            return s;
          })
        };
      }
      return p;
    }));
  };

  const updateAuditRow = (pId, sId, rowIndex, field, value) => {
    setParameters(prev => prev.map(p => {
      if (p.id === pId) {
        return {
          ...p,
          subsections: p.subsections.map(s => {
            if (s.id === sId) {
              const newList = [...s.auditChecklist];
              newList[rowIndex] = { ...newList[rowIndex], [field]: value };
              
              // Auto-calculate obtained marks if response changes
              if (field === 'response') {
                newList[rowIndex].obtained_marks = value === 'Yes' ? newList[rowIndex].max_marks : 0.0;
              }
              
              // Sync achievement score (sum of obtained marks)
              const totalObtained = newList.reduce((acc, item) => acc + (parseFloat(item.obtained_marks) || 0), 0);
              return { ...s, auditChecklist: newList, achievement: totalObtained };
            }
            return s;
          })
        };
      }
      return p;
    }));
  };

  const removeAuditRow = (pId, sId, rowIndex) => {
    setParameters(prev => prev.map(p => {
      if (p.id === pId) {
        return {
          ...p,
          subsections: p.subsections.map(s => {
            if (s.id === sId) {
              const newList = s.auditChecklist.filter((_, i) => i !== rowIndex);
              const totalObtained = newList.reduce((acc, item) => acc + (parseFloat(item.obtained_marks) || 0), 0);
              return { ...s, auditChecklist: newList, achievement: totalObtained };
            }
            return s;
          })
        };
      }
      return p;
    }));
  };

  const exportAuditTemplate = (sub) => {
    // Ensure we always have headers, even if the checklist is empty
    const headers = ['S.No', 'Check Points', 'MM - 5', 'Yes/No', 'Obtained Marks', 'Remarks'];
    const data = (sub.auditChecklist && sub.auditChecklist.length > 0) 
      ? sub.auditChecklist.map(item => ({
          'S.No': item.sno,
          'Check Points': item.checkpoint,
          'MM - 5': item.max_marks,
          'Yes/No': item.response,
          'Obtained Marks': item.obtained_marks,
          'Remarks': item.remarks
        }))
      : [Object.fromEntries(headers.map(h => [h, '']))]; // One blank row with headers

    const ws = XLSX.utils.json_to_sheet(data, { header: headers });
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Audit Checklist");
    XLSX.writeFile(wb, `${sub.name}_Audit_Template.xlsx`);
    showSuccess('Audit template exported with headers');
  };

  const importAuditData = (pId, sId, event) => {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      const data = new Uint8Array(e.target.result);
      const workbook = XLSX.read(data, { type: 'array' });
      const sheetName = workbook.SheetNames[0];
      const worksheet = workbook.Sheets[sheetName];
      const json = XLSX.utils.sheet_to_json(worksheet);

      const updatedChecklist = json.map(row => ({
        sno: parseInt(row['S.No']) || 0,
        checkpoint: row['Check Points'] || '',
        max_marks: parseFloat(row['MM - 5']) || 5.0,
        response: row['Yes/No'] || 'No',
        obtained_marks: parseFloat(row['Obtained Marks']) || 0.0,
        remarks: row['Remarks'] || ''
      }));

      setParameters(prev => prev.map(p => {
        if (p.id === pId) {
          return {
            ...p,
            subsections: p.subsections.map(s => {
              if (s.id === sId) {
                const totalObtained = updatedChecklist.reduce((acc, item) => acc + (parseFloat(item.obtained_marks) || 0), 0);
                return { ...s, auditChecklist: updatedChecklist, achievement: totalObtained };
              }
              return s;
            })
          };
        }
        return p;
      }));
      showSuccess('Audit data imported and scores updated');
    };
    reader.readAsArrayBuffer(file);
    event.target.value = ''; // Reset the input value so that the next select always triggers onChange!
  };

  const addTeamEngagementRow = (pId, sId) => {
    setParameters(prev => prev.map(p => {
      if (p.id === pId) {
        return {
          ...p,
          subsections: p.subsections.map(s => {
            if (s.id === sId) {
              const nextSno = (s.teamEngagementChecklist?.length || 0) + 1;
              return {
                ...s,
                teamEngagementChecklist: [
                  ...(s.teamEngagementChecklist || []),
                  { sno: nextSno, question: '', min_marks: 0.0, review: '' }
                ]
              };
            }
            return s;
          })
        };
      }
      return p;
    }));
  };

  const updateTeamEngagementRow = (pId, sId, rowIndex, field, value) => {
    setParameters(prev => prev.map(p => {
      if (p.id === pId) {
        return {
          ...p,
          subsections: p.subsections.map(s => {
            if (s.id === sId) {
              const newList = [...(s.teamEngagementChecklist || [])];
              newList[rowIndex] = { ...newList[rowIndex], [field]: value };
              return { ...s, teamEngagementChecklist: newList };
            }
            return s;
          })
        };
      }
      return p;
    }));
  };

  const removeTeamEngagementRow = (pId, sId, rowIndex) => {
    setParameters(prev => prev.map(p => {
      if (p.id === pId) {
        return {
          ...p,
          subsections: p.subsections.map(s => {
            if (s.id === sId) {
              const newList = (s.teamEngagementChecklist || []).filter((_, i) => i !== rowIndex);
              return { ...s, teamEngagementChecklist: newList };
            }
            return s;
          })
        };
      }
      return p;
    }));
  };

  const exportTeamEngagementTemplate = (sub) => {
    const headers = ['S.No', 'Question', 'Minimum Marks', 'Review'];
    const data = (sub.teamEngagementChecklist && sub.teamEngagementChecklist.length > 0) 
      ? sub.teamEngagementChecklist.map(item => ({
          'S.No': item.sno,
          'Question': item.question,
          'Minimum Marks': item.min_marks,
          'Review': item.review || ''
        }))
      : [Object.fromEntries(headers.map(h => [h, '']))];

    const ws = XLSX.utils.json_to_sheet(data, { header: headers });
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Team Engagement");
    XLSX.writeFile(wb, `${sub.name}_Team_Engagement_Template.xlsx`);
    showSuccess('Team Engagement template exported with headers');
  };

  const importTeamEngagementData = (pId, sId, event) => {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      const data = new Uint8Array(e.target.result);
      const workbook = XLSX.read(data, { type: 'array' });
      const sheetName = workbook.SheetNames[0];
      const worksheet = workbook.Sheets[sheetName];
      const json = XLSX.utils.sheet_to_json(worksheet);

      const updatedChecklist = json.map(row => ({
        sno: parseInt(row['S.No']) || 0,
        question: row['Question'] || '',
        min_marks: parseFloat(row['Minimum Marks']) || 0.0,
        review: row['Review'] || ''
      }));

      setParameters(prev => prev.map(p => {
        if (p.id === pId) {
          return {
            ...p,
            subsections: p.subsections.map(s => {
              if (s.id === sId) {
                return { ...s, teamEngagementChecklist: updatedChecklist };
              }
              return s;
            })
          };
        }
        return p;
      }));
      showSuccess('Team Engagement data imported successfully');
    };
    reader.readAsArrayBuffer(file);
    event.target.value = ''; // Reset the input value so that the next select always triggers onChange!
  };

  const addBudgetAdherenceRow = (pId, sId) => {
    setParameters(prev => prev.map(p => {
      if (p.id === pId) {
        return {
          ...p,
          subsections: p.subsections.map(s => {
            if (s.id === sId) {
              const nextSno = (s.budgetAdherenceChecklist?.length || 0) + 1;
              return {
                ...s,
                budgetAdherenceChecklist: [
                  ...(s.budgetAdherenceChecklist || []),
                  { 
                    sno: nextSno, 
                    particulars: '', 
                    head: '', 
                    subhead: '', 
                    rate: 0.0, 
                    target: 0.0, 
                    actual: 0.0, 
                    gap: 0.0, 
                    raised_by: '', 
                    raised_to: '', 
                    reason: '' 
                  }
                ]
              };
            }
            return s;
          })
        };
      }
      return p;
    }));
  };

  const updateBudgetAdherenceRow = (pId, sId, rowIndex, field, value) => {
    setParameters(prev => prev.map(p => {
      if (p.id === pId) {
        return {
          ...p,
          subsections: p.subsections.map(s => {
            if (s.id === sId) {
              const newList = [...(s.budgetAdherenceChecklist || [])];
              const updatedRow = { ...newList[rowIndex], [field]: value };
              
              if (field === 'target' || field === 'actual' || field === 'rate') {
                const targetVal = field === 'target' ? parseFloat(value) || 0 : parseFloat(updatedRow.target) || 0;
                const actualVal = field === 'actual' ? parseFloat(value) || 0 : parseFloat(updatedRow.actual) || 0;
                updatedRow.gap = parseFloat((targetVal - actualVal).toFixed(2));
              }
              
              newList[rowIndex] = updatedRow;
              return { ...s, budgetAdherenceChecklist: newList };
            }
            return s;
          })
        };
      }
      return p;
    }));
  };

  const removeBudgetAdherenceRow = (pId, sId, rowIndex) => {
    setParameters(prev => prev.map(p => {
      if (p.id === pId) {
        return {
          ...p,
          subsections: p.subsections.map(s => {
            if (s.id === sId) {
              const newList = (s.budgetAdherenceChecklist || []).filter((_, i) => i !== rowIndex);
              return { ...s, budgetAdherenceChecklist: newList };
            }
            return s;
          })
        };
      }
      return p;
    }));
  };

  const exportBudgetAdherenceTemplate = (sub) => {
    const headers = [
      'S.No', 'Particulars', 'Particulars Head', 'Head Subhead', 
      'Rate', 'Target', 'Actual', 'Gap', 'Raised By', 'Raised To', 'Reason'
    ];
    const data = (sub.budgetAdherenceChecklist && sub.budgetAdherenceChecklist.length > 0)
      ? sub.budgetAdherenceChecklist.map(item => ({
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
    XLSX.writeFile(wb, `${sub.name}_Budget_Cost_Adherence_Template.xlsx`);
    showSuccess('Budget Adherence template exported with headers');
  };

  const importBudgetAdherenceData = (pId, sId, event) => {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      const data = new Uint8Array(e.target.result);
      const workbook = XLSX.read(data, { type: 'array' });
      const sheetName = workbook.SheetNames[0];
      const worksheet = workbook.Sheets[sheetName];
      const json = XLSX.utils.sheet_to_json(worksheet);

      const updatedChecklist = json.map(row => {
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

      setParameters(prev => prev.map(p => {
        if (p.id === pId) {
          return {
            ...p,
            subsections: p.subsections.map(s => {
              if (s.id === sId) {
                return { ...s, budgetAdherenceChecklist: updatedChecklist };
              }
              return s;
            })
          };
        }
        return p;
      }));
      showSuccess('Budget Cost Adherence data imported successfully');
    };
    reader.readAsArrayBuffer(file);
    event.target.value = '';
  };

  const handleSave = async () => {
    const totalWeightage = parameters.reduce((acc, p) => acc + (parseFloat(p.weightage) || 0), 0);
    if (totalWeightage !== 100) {
      showError('Total weightage across all parameters must be exactly 100%');
      return;
    }

    const totalScore = parameters.reduce((acc, p) => {
      const pScore = p.subsections.reduce((sAcc, s) => sAcc + parseFloat(calculateScore(s, p.isReverse)), 0);
      return acc + pScore;
    }, 0);

    setIsSaving(true);
    try {
      await api.post('/orm', {
        company_id: user.company_id,
        parameters: sanitizeORMParameters(parameters),
        total_weightage: totalWeightage,
        total_score: totalScore
      });
      showSuccess('ORM Setup saved successfully');
      navigate('/orm');
    } catch (error) {
      console.error('Error saving ORM:', error);
      const detail = error.response?.data?.detail;
      const errorMsg = typeof detail === 'string' 
        ? detail 
        : Array.isArray(detail) 
          ? detail.map(d => `${d.loc[d.loc.length-1]}: ${d.msg}`).join(', ')
          : 'Failed to save ORM Setup. Please check all fields.';
      showError(errorMsg);
    } finally {
      setIsSaving(false);
    }
  };

  const handleSaveProgress = async (paramName) => {
    const totalWeightage = parameters.reduce((acc, p) => acc + (parseFloat(p.weightage) || 0), 0);
    const totalScore = parameters.reduce((acc, p) => {
      const pScore = p.subsections.reduce((sAcc, s) => sAcc + parseFloat(calculateScore(s, p.isReverse)), 0);
      return acc + pScore;
    }, 0);

    setIsSaving(true);
    try {
      await api.post('/orm', {
        company_id: user.company_id,
        parameters: sanitizeORMParameters(parameters),
        total_weightage: totalWeightage,
        total_score: totalScore
      });
      showSuccess(`Audit configuration for "${paramName}" saved successfully`);
    } catch (error) {
      console.error('Error saving ORM progress:', error);
      const detail = error.response?.data?.detail;
      const errorMsg = typeof detail === 'string' 
        ? detail 
        : Array.isArray(detail) 
          ? detail.map(d => `${d.loc[d.loc.length-1]}: ${d.msg}`).join(', ')
          : 'Failed to save progress. Please check all fields.';
      showError(errorMsg);
    } finally {
      setIsSaving(false);
    }
  };

  const UserSelector = ({ selectedUsers, onToggle, label, compact = false }) => {
    const [isOpen, setIsOpen] = useState(false);
    const buttonRef = useRef(null);
    const [coords, setCoords] = useState({ top: 0, left: 0, openUp: false });

    const PANEL_WIDTH = 288; // w-72
    const PANEL_MAX_HEIGHT = 360; // header + max-h-64 list + padding

    const recomputePosition = () => {
      const el = buttonRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom;
      const openUp = spaceBelow < PANEL_MAX_HEIGHT && rect.top > spaceBelow;
      const top = openUp ? rect.top - 8 : rect.bottom + 8;
      let left = rect.left;
      // Keep panel within viewport horizontally
      const maxLeft = window.innerWidth - PANEL_WIDTH - 8;
      if (left > maxLeft) left = Math.max(8, maxLeft);
      setCoords({ top, left, openUp });
    };

    useLayoutEffect(() => {
      if (!isOpen) return;
      recomputePosition();
      const handle = () => recomputePosition();
      window.addEventListener('scroll', handle, true);
      window.addEventListener('resize', handle);
      return () => {
        window.removeEventListener('scroll', handle, true);
        window.removeEventListener('resize', handle);
      };
    }, [isOpen]);

    return (
      <div className="relative">
        <button
          ref={buttonRef}
          onClick={() => setIsOpen(!isOpen)}
          className={`flex items-center gap-2 bg-[var(--input-bg)] border border-[var(--border)] rounded-xl hover:border-blue-500/50 transition-all font-bold ${compact ? 'px-2 py-1 text-[10px]' : 'px-3 py-1.5 text-xs'}`}
        >
          <Users size={compact ? 12 : 14} className="text-blue-500" />
          <span className="text-[var(--text-main)] truncate max-w-[100px]">
            {selectedUsers.length > 0 ? `${selectedUsers.length} Users` : label || 'Assign'}
          </span>
          <ChevronDown size={14} className={`transition-transform ${isOpen ? 'rotate-180' : ''}`} />
        </button>

        {isOpen && createPortal(
          <AnimatePresence>
            <div className="fixed inset-0 z-[60]" onClick={() => setIsOpen(false)} />
            <motion.div
              initial={{ opacity: 0, y: coords.openUp ? -10 : 10, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: coords.openUp ? -10 : 10, scale: 0.95 }}
              style={{
                position: 'fixed',
                top: coords.openUp ? undefined : coords.top,
                bottom: coords.openUp ? window.innerHeight - coords.top : undefined,
                left: coords.left,
                width: PANEL_WIDTH,
              }}
              className="bg-[var(--bg-card)] border border-[var(--border)] rounded-2xl shadow-2xl z-[70] overflow-hidden"
            >
              <div className="p-3 border-b border-[var(--border)] bg-[var(--input-bg)]/50 flex justify-between items-center">
                <span className="text-[10px] font-black text-[var(--text-muted)] uppercase tracking-widest">Select Team</span>
                <button onClick={() => setIsOpen(false)} className="p-1 hover:bg-red-500/10 text-red-500 rounded-lg"><X size={14} /></button>
              </div>
              <div className="max-h-64 overflow-y-auto p-1.5 space-y-0.5">
                {availableUsers.map(u => {
                  const isSelected = selectedUsers.includes(u._id);
                  return (
                    <button
                      key={u._id}
                      onClick={() => onToggle(u._id)}
                      className={`w-full flex items-center gap-3 p-2 rounded-lg transition-all text-left ${isSelected ? 'bg-blue-600 text-white' : 'hover:bg-[var(--input-bg)] text-[var(--text-muted)]'}`}
                    >
                      <div className={`w-4 h-4 rounded-md border flex items-center justify-center transition-all ${isSelected ? 'bg-white border-white' : 'border-[var(--border)] bg-transparent'}`}>
                        {isSelected && <CheckCircle2 size={10} className="text-blue-500" />}
                      </div>
                      <div className="flex flex-col">
                        <span className={`text-[11px] font-black leading-none ${isSelected ? 'text-white' : 'text-[var(--text-main)]'}`}>{u.full_name || u.first_name}</span>
                        <span className={`text-[9px] font-bold uppercase tracking-tighter mt-0.5 ${isSelected ? 'text-white/70' : 'opacity-60'}`}>{u.role}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </motion.div>
          </AnimatePresence>,
          document.body
        )}
      </div>
    );
  };

  const steps = [
    { id: 1, title: 'Logic', icon: <Settings2 size={18} />, description: 'Rules' },
    { id: 2, title: 'Hierarchy', icon: <Layers size={18} />, description: 'Weights' },
    { id: 3, title: 'Alerts', icon: <BellRing size={18} />, description: 'Schedules' },
    { id: 4, title: 'Audit', icon: <ClipboardCheck size={18} />, description: 'Verification' }
  ];

  if (isLoading) return null;

  const currentParam = parameters[activeParamIndex];

  return (
    <div className="p-4 max-w-7xl mx-auto space-y-6 bg-[var(--bg-main)] min-h-screen">
      {/* Compact Header */}
      <div className="flex justify-between items-center bg-[var(--bg-card)] p-4 rounded-2xl border border-[var(--border)] shadow-sm">
        <div className="flex items-center gap-4">
          <button 
            onClick={() => navigate('/orm')}
            className="p-2 bg-[var(--input-bg)] text-[var(--text-muted)] hover:text-blue-500 rounded-xl transition-all"
          >
            <ArrowLeft size={18} />
          </button>
          <div>
            <h1 className="text-xl font-black text-[var(--text-main)] flex items-center gap-2">
              <ShieldCheck size={20} className="text-blue-500" />
              Strategic ORM Designer
            </h1>
            <p className="text-[10px] font-bold text-[var(--text-muted)] opacity-60">Control Center & Audit Policy Configuration</p>
          </div>
        </div>

        <div className="flex items-center gap-6">
          <div className="flex flex-col items-end">
            <span className="text-[9px] font-black uppercase tracking-widest text-[var(--text-muted)]">Setup Completion</span>
            <div className="flex items-center gap-2">
              <div className="w-24 h-1.5 bg-[var(--input-bg)] rounded-full overflow-hidden">
                <motion.div 
                  initial={{ width: 0 }}
                  animate={{ width: `${(currentStep / 4) * 100}%` }}
                  className="h-full bg-blue-500"
                />
              </div>
              <span className="text-xs font-black text-blue-500">{Math.round((currentStep / 4) * 100)}%</span>
            </div>
          </div>
        </div>
      </div>

      {/* Compact Stepper */}
      <div className="flex items-center justify-center gap-2 px-10 relative">
        <div className="absolute top-1/2 left-20 right-20 h-0.5 bg-[var(--border)] -translate-y-1/2 z-0" />
        {steps.map((step) => (
          <button 
            key={step.id} 
            onClick={() => step.id <= currentStep + 1 && setCurrentStep(step.id)}
            className="relative z-10 flex flex-col items-center group flex-1"
          >
            <div className={`w-10 h-10 rounded-xl flex items-center justify-center transition-all duration-300 border-2 ${currentStep >= step.id ? 'bg-blue-600 border-blue-500 text-white shadow-lg shadow-blue-500/20' : 'bg-[var(--bg-card)] border-[var(--border)] text-[var(--text-muted)]'}`}>
              {currentStep > step.id ? <CheckCircle2 size={20} /> : step.icon}
            </div>
            <span className={`text-[10px] font-black uppercase tracking-tighter mt-2 transition-colors ${currentStep === step.id ? 'text-blue-500' : 'text-[var(--text-muted)]'}`}>{step.title}</span>
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-12 gap-6 items-start">
        {/* Compact Sidebar */}
        <div className="md:col-span-3 space-y-2 bg-[var(--bg-card)] p-2 rounded-2xl border border-[var(--border)]">
          <span className="text-[9px] font-black uppercase tracking-widest text-[var(--text-muted)] ml-2">Main Parameters</span>
          {parameters.map((p, idx) => (
            <button
              key={p.id}
              onClick={() => setActiveParamIndex(idx)}
              className={`w-full group flex items-center gap-3 p-3 rounded-xl transition-all duration-200 ${activeParamIndex === idx ? 'bg-blue-600 text-white shadow-md' : 'hover:bg-[var(--input-bg)] text-[var(--text-muted)]'}`}
            >
              <div className={`w-6 h-6 rounded-lg flex items-center justify-center text-[10px] font-black ${activeParamIndex === idx ? 'bg-white/20' : 'bg-blue-500/10 text-blue-500'}`}>
                {idx + 1}
              </div>
              <span className="text-xs font-black truncate text-left flex-1">{p.name}</span>
            </button>
          ))}
        </div>

        {/* Content Area */}
        <div className="md:col-span-9 bg-[var(--bg-card)] rounded-2xl border border-[var(--border)] overflow-hidden flex flex-col min-h-[600px] shadow-sm">
          {/* Active Step Content */}
          <div className="p-6 flex-1">
            <AnimatePresence mode="wait">
              <motion.div
                key={`${currentStep}-${activeParamIndex}`}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="space-y-6"
              >
                {/* Parameter Context Header */}
                <div className="flex justify-between items-center border-b border-[var(--border)] pb-4">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-blue-500/10 rounded-lg text-blue-500">
                      {steps.find(s => s.id === currentStep)?.icon}
                    </div>
                    <div>
                      <h2 className="text-lg font-black text-[var(--text-main)]">{currentParam.name}</h2>
                      <p className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest">{steps.find(s => s.id === currentStep)?.description}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="flex items-center gap-2 px-3 py-1.5 bg-blue-500/5 rounded-xl border border-blue-500/10">
                      <PieChart size={14} className="text-blue-500" />
                      <span className="text-xs font-black text-blue-500">{currentParam.weightage}%</span>
                    </div>
                  </div>
                </div>

                {currentStep === 1 && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="space-y-4">
                      <div className="space-y-1.5">
                        <label className="text-[9px] font-black uppercase tracking-widest text-[var(--text-muted)] ml-1">Parameter Display Name</label>
                        <input 
                          value={currentParam.name}
                          onChange={(e) => updateParameter(currentParam.id, 'name', e.target.value)}
                          className="w-full bg-[var(--input-bg)] border border-[var(--border)] rounded-xl px-4 py-2.5 font-black text-[var(--text-main)] focus:border-blue-500 outline-none transition-all text-sm"
                        />
                      </div>
                      
                      <div className="p-4 bg-[var(--input-bg)]/30 rounded-2xl border border-[var(--border)] flex items-center justify-between">
                        <div className="space-y-0.5">
                          <h4 className="text-xs font-black text-[var(--text-main)]">Scoring Formula</h4>
                          <p className="text-[9px] font-bold text-[var(--text-muted)]">{currentParam.isReverse ? 'Lower is better (Cost/Time)' : 'Higher is better (Revenue/Score)'}</p>
                        </div>
                        <button 
                          onClick={() => updateParameter(currentParam.id, 'isReverse', !currentParam.isReverse)}
                          className={`px-4 py-2 rounded-xl text-[10px] font-black transition-all border ${currentParam.isReverse ? 'bg-orange-500 border-orange-600 text-white shadow-md' : 'bg-blue-600 border-blue-700 text-white shadow-md'}`}
                        >
                          {currentParam.isReverse ? 'REVERSE' : 'STANDARD'}
                        </button>
                      </div>
                    </div>

                    <div className="p-4 bg-blue-500/5 rounded-2xl border border-blue-500/10 space-y-3">
                      <div className="flex items-center gap-2 text-blue-500">
                        <ShieldCheck size={16} />
                        <h4 className="text-[10px] font-black uppercase tracking-widest">Global Assignment</h4>
                      </div>
                      <p className="text-[10px] font-bold text-[var(--text-muted)] opacity-60 italic">These users oversee all subsections within this parameter.</p>
                      <UserSelector 
                        selectedUsers={currentParam.assignedUsers || []}
                        onToggle={(uid) => {
                          const current = currentParam.assignedUsers || [];
                          const updated = current.includes(uid) ? current.filter(id => id !== uid) : [...current, uid];
                          updateParameter(currentParam.id, 'assignedUsers', updated);
                        }}
                      />
                    </div>
                  </div>
                )}

                {currentStep === 2 && (
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <span className="text-[9px] font-black uppercase tracking-widest text-[var(--text-muted)]">Parameter Hierarchy</span>
                      <button 
                        onClick={() => addSubsection(currentParam.id)}
                        className="flex items-center gap-1 px-3 py-1.5 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-all font-black text-[9px] uppercase"
                      >
                        <Plus size={12} /> Add Subsection
                      </button>
                    </div>

                    <div className="space-y-2 max-h-[350px] overflow-y-auto pr-2 custom-scrollbar">
                      {currentParam.subsections.map((sub, sIdx) => (
                        <div 
                          key={sub.id}
                          className="flex items-center gap-3 p-3 bg-[var(--input-bg)]/20 hover:bg-[var(--input-bg)]/40 rounded-xl border border-[var(--border)] transition-all"
                        >
                          <div className="flex-1">
                            <input 
                              value={sub.name}
                              onChange={(e) => updateSubsection(currentParam.id, sub.id, 'name', e.target.value)}
                              placeholder="e.g. Sales, Service, etc."
                              className="w-full bg-transparent border-none p-0 text-xs font-black text-[var(--text-main)] focus:ring-0"
                            />
                          </div>

                          <div className="w-24">
                            <div className="flex items-center bg-[var(--input-bg)] border border-[var(--border)] rounded-lg px-2 py-1">
                              <span className="text-[9px] font-bold text-[var(--text-muted)] mr-1">Weight:</span>
                              <input 
                                type="number"
                                value={sub.weightage}
                                onChange={(e) => updateSubsection(currentParam.id, sub.id, 'weightage', e.target.value)}
                                className="w-full bg-transparent border-none p-0 text-xs font-black text-blue-500 outline-none"
                              />
                            </div>
                          </div>

                          <button 
                            onClick={() => updateSubsection(currentParam.id, sub.id, 'isPercentage', !sub.isPercentage)}
                            className={`w-14 py-1.5 rounded-md text-[9px] font-black border transition-all ${sub.isPercentage ? 'bg-indigo-500/10 text-indigo-500 border-indigo-500/20' : 'bg-slate-500/10 text-slate-500 border-slate-500/20'}`}
                          >
                            {sub.isPercentage ? 'PERC %' : 'NUM #'}
                          </button>

                          <button 
                            onClick={() => removeSubsection(currentParam.id, sub.id)}
                            className="p-1.5 text-red-500 hover:bg-red-500/10 rounded-lg transition-all"
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {currentStep === 3 && (
                  <div className="space-y-3 max-h-[400px] overflow-y-auto pr-2 custom-scrollbar">
                    {currentParam.subsections.map((sub) => (
                      <div key={sub.id} className="p-3 bg-[var(--input-bg)]/20 rounded-2xl border border-[var(--border)] flex items-center justify-between gap-4">
                        <div className="w-1/3">
                          <h4 className="text-xs font-black text-[var(--text-main)] truncate">{sub.name}</h4>
                          <span className="text-[9px] font-black text-blue-500 uppercase tracking-tighter">Current Weight: {sub.weightage}%</span>
                        </div>

                        <div className="flex-1">
                           <UserSelector 
                              compact
                              label="Assign Doer"
                              selectedUsers={sub.assignedUsers || []}
                              onToggle={(uid) => {
                                const current = sub.assignedUsers || [];
                                const updated = current.includes(uid) ? current.filter(id => id !== uid) : [...current, uid];
                                updateSubsection(currentParam.id, sub.id, 'assignedUsers', updated);
                              }}
                           />
                        </div>

                        <div className="w-1/3 flex items-center gap-2">
                            <select 
                              value={sub.frequency || 'none'}
                              onChange={(e) => updateSubsection(currentParam.id, sub.id, 'frequency', e.target.value)}
                              className="w-full bg-[var(--bg-card)] border border-[var(--border)] rounded-lg px-2 py-1.5 text-[10px] font-bold outline-none focus:border-blue-500"
                            >
                              <option value="none">No Reminders</option>
                              <option value="monthly">Monthly</option>
                              <option value="quarterly">Quarterly</option>
                            </select>
                            {sub.frequency && sub.frequency !== 'none' && (
                              <input 
                                type="number"
                                min="1" max="31"
                                value={sub.dayOfMonth || 1}
                                onChange={(e) => updateSubsection(currentParam.id, sub.id, 'dayOfMonth', parseInt(e.target.value))}
                                className="w-10 bg-blue-600 text-white rounded-lg px-1 py-1.5 text-[10px] font-black text-center shadow-md"
                              />
                            )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {currentStep === 4 && (
                  <div className="space-y-4">
                    {/* Top Level Audit Settings for Param Subsections */}
                    <div className="grid grid-cols-1 md:grid-cols-12 gap-6 h-full">
                        {/* Subsection Picker for Audit */}
                        <div className="md:col-span-4 space-y-2 max-h-[450px] overflow-y-auto pr-1">
                            <span className="text-[9px] font-black uppercase tracking-widest text-[var(--text-muted)] ml-2">Choose Subsection</span>
                            {currentParam.subsections.map((sub, sIdx) => (
                                <button
                                    key={sub.id}
                                    onClick={() => {
                                      setParameters(prev => prev.map(p => {
                                        if (p.id === currentParam.id) {
                                          return {
                                            ...p,
                                            subsections: p.subsections.map(s => {
                                              if (s.id === sub.id) {
                                                const nextHasAudit = !s.hasAudit;
                                                return {
                                                  ...s,
                                                  hasAudit: nextHasAudit,
                                                  auditName: nextHasAudit ? (s.auditName || `${s.name} Audit`) : s.auditName
                                                };
                                              } else {
                                                return {
                                                  ...s,
                                                  hasAudit: false
                                                };
                                              }
                                            })
                                          };
                                        }
                                        return p;
                                      }));
                                    }}
                                    className={`w-full p-3 rounded-xl border text-left transition-all ${sub.hasAudit ? 'bg-amber-500/10 border-amber-500/30 text-amber-700' : 'bg-[var(--bg-card)] border-[var(--border)] text-[var(--text-muted)] opacity-50 hover:opacity-100'}`}
                                >
                                    <div className="flex items-center justify-between">
                                        <span className="text-[11px] font-black">{sub.name}</span>
                                        {sub.hasAudit && <CheckCircle2 size={12} />}
                                    </div>
                                    <div className="text-[9px] font-bold mt-1 uppercase">MM: {sub.auditChecklist?.reduce((acc, i) => acc + (parseFloat(i.max_marks) || 0), 0) || 0}</div>
                                </button>
                            ))}
                        </div>

                        {/* Audit Details Area */}
                        <div className="md:col-span-8 bg-[var(--input-bg)]/10 rounded-2xl border border-[var(--border)] p-4 space-y-4 overflow-hidden flex flex-col">
                            {currentParam.subsections.find(s => s.hasAudit) ? (
                                <>
                                    {/* Sub-Selection for which Audit to edit */}
                                    {(() => {
                                        const sub = currentParam.subsections.find(s => s.hasAudit);
                                        if (!sub) return null;

                                        return (
                                            <div className="space-y-4 flex-1 flex flex-col overflow-hidden">
                                                <div className="flex items-center justify-between gap-4">
                                                    <div className="flex-1 space-y-1">
                                                        <label className="text-[9px] font-black uppercase tracking-widest text-[var(--text-muted)]">Unit Name</label>
                                                        <input 
                                                            value={sub.unitName || ''}
                                                            onChange={(e) => updateSubsection(currentParam.id, sub.id, 'unitName', e.target.value)}
                                                            placeholder="e.g. Plant 1, HQ, North Region"
                                                            className="w-full bg-[var(--bg-card)] border border-[var(--border)] rounded-lg px-3 py-1.5 text-xs font-black outline-none focus:border-amber-500"
                                                        />
                                                    </div>
                                                    <div className="flex-1 space-y-1">
                                                        <label className="text-[9px] font-black uppercase tracking-widest text-[var(--text-muted)]">Audit Title</label>
                                                        <input 
                                                            value={sub.auditName || ''}
                                                            onChange={(e) => updateSubsection(currentParam.id, sub.id, 'auditName', e.target.value)}
                                                            className="w-full bg-[var(--bg-card)] border border-[var(--border)] rounded-lg px-3 py-1.5 text-xs font-black outline-none focus:border-amber-500"
                                                        />
                                                    </div>
                                                </div>

                                                {(() => {
                                                    const isProcessScore = currentParam.id === 'p2' || currentParam.name === 'Process score';
                                                    const isNpsOrCsi = currentParam.id === 'p3' || currentParam.name === 'NPS OR CSI';
                                                    const isBudgetAdherence = currentParam.id === 'p5' || currentParam.name === 'Budget Cost Adherence';

                                                    if (isProcessScore) {
                                                        return (
                                                            <>
                                                                <div className="flex items-center justify-between border-y border-[var(--border)] py-2">
                                                                    <span className="text-[10px] font-black uppercase text-amber-600">Checklist Builder</span>
                                                                    <div className="flex items-center gap-2">
                                                                        <button 
                                                                            onClick={() => exportAuditTemplate(sub)}
                                                                            className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-500 text-white rounded-lg font-black text-[9px] uppercase shadow-md hover:bg-indigo-600 transition-all"
                                                                        >
                                                                            <FileDown size={12} /> Export Format
                                                                        </button>
                                                                        <label className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 text-white rounded-lg font-black text-[9px] uppercase shadow-md cursor-pointer hover:bg-emerald-700 transition-all">
                                                                            <FileUp size={12} /> Import Filled
                                                                            <input type="file" className="hidden" accept=".xlsx, .xls" onChange={(e) => importAuditData(currentParam.id, sub.id, e)} />
                                                                        </label>
                                                                        <button 
                                                                            onClick={() => handleSaveProgress(currentParam.name)}
                                                                            disabled={isSaving}
                                                                            className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-black text-[9px] uppercase shadow-md disabled:opacity-50 transition-all"
                                                                        >
                                                                            {isSaving ? <Clock className="animate-spin" size={12} /> : <Save size={12} />} Save Audit Setup
                                                                        </button>
                                                                    </div>
                                                                </div>

                                                                <div className="flex-1 overflow-y-auto pr-1 space-y-2 custom-scrollbar">
                                                                    <table className="w-full text-left border-collapse">
                                                                        <thead>
                                                                            <tr className="text-[9px] font-black uppercase text-[var(--text-muted)] border-b border-[var(--border)]">
                                                                                <th className="pb-2 w-10 text-center">S.No</th>
                                                                                <th className="pb-2">Check Points</th>
                                                                                <th className="pb-2 w-16">MM-5</th>
                                                                                <th className="pb-2 w-20">Yes/No</th>
                                                                                <th className="pb-2 w-16">Obtained</th>
                                                                                <th className="pb-2 w-24">Remarks</th>
                                                                                <th className="pb-2 w-10"></th>
                                                                            </tr>
                                                                        </thead>
                                                                        <tbody>
                                                                            {(sub.auditChecklist || []).map((item, rIdx) => (
                                                                                <tr key={rIdx} className="border-b border-[var(--border)] last:border-0 group">
                                                                                    <td className="py-2 text-center text-[10px] font-bold">{item.sno}</td>
                                                                                    <td className="py-2">
                                                                                        <input 
                                                                                            value={item.checkpoint}
                                                                                            onChange={(e) => updateAuditRow(currentParam.id, sub.id, rIdx, 'checkpoint', e.target.value)}
                                                                                            className="w-full bg-transparent border-none text-[10px] font-black p-0 focus:ring-0"
                                                                                            placeholder="Define Checkpoint..."
                                                                                        />
                                                                                    </td>
                                                                                    <td className="py-2">
                                                                                        <input 
                                                                                            type="number"
                                                                                            value={item.max_marks}
                                                                                            onChange={(e) => updateAuditRow(currentParam.id, sub.id, rIdx, 'max_marks', e.target.value)}
                                                                                            className="w-12 bg-[var(--bg-card)] border border-[var(--border)] rounded p-1 text-[10px] font-black"
                                                                                        />
                                                                                    </td>
                                                                                    <td className="py-2">
                                                                                        <select 
                                                                                            value={item.response}
                                                                                            onChange={(e) => updateAuditRow(currentParam.id, sub.id, rIdx, 'response', e.target.value)}
                                                                                            className="w-full bg-[var(--bg-card)] border border-[var(--border)] rounded p-1 text-[10px] font-black outline-none"
                                                                                        >
                                                                                            <option value="Yes">Yes</option>
                                                                                            <option value="No">No</option>
                                                                                        </select>
                                                                                    </td>
                                                                                    <td className="py-2">
                                                                                        <span className={`text-[10px] font-black ${item.obtained_marks > 0 ? 'text-green-500' : 'text-red-500'}`}>{item.obtained_marks}</span>
                                                                                    </td>
                                                                                    <td className="py-2">
                                                                                        <input 
                                                                                            value={item.remarks}
                                                                                            onChange={(e) => updateAuditRow(currentParam.id, sub.id, rIdx, 'remarks', e.target.value)}
                                                                                            className="w-full bg-transparent border-none text-[9px] font-bold p-0 focus:ring-0 opacity-50 group-hover:opacity-100"
                                                                                            placeholder="Remarks..."
                                                                                        />
                                                                                    </td>
                                                                                    <td className="py-2 text-center">
                                                                                        <button onClick={() => removeAuditRow(currentParam.id, sub.id, rIdx)} className="text-red-500 opacity-0 group-hover:opacity-100"><X size={12}/></button>
                                                                                    </td>
                                                                                </tr>
                                                                            ))}
                                                                        </tbody>
                                                                    </table>
                                                                    <button 
                                                                        onClick={() => addAuditRow(currentParam.id, sub.id)}
                                                                        className="w-full py-2 border-2 border-dashed border-[var(--border)] rounded-xl text-[10px] font-black text-[var(--text-muted)] hover:text-blue-500 hover:border-blue-500/30 transition-all flex items-center justify-center gap-2"
                                                                    >
                                                                        <Plus size={12} /> Add New Checkpoint
                                                                    </button>
                                                                </div>
                                                            </>
                                                        );
                                                    } else if (isNpsOrCsi) {
                                                        return (
                                                            <div className="flex-1 flex flex-col justify-between pt-4 space-y-6">
                                                                <div className="p-5 bg-gradient-to-r from-emerald-500/5 to-teal-500/5 rounded-2xl border border-emerald-500/10 space-y-3">
                                                                    <div className="flex items-center gap-2 text-emerald-600">
                                                                        <ClipboardCheck size={20} />
                                                                        <h4 className="text-sm font-black uppercase tracking-wider">Google Sheets & Forms Setup</h4>
                                                                    </div>
                                                                    <p className="text-xs font-medium text-[var(--text-muted)] leading-relaxed">
                                                                        For the <strong className="text-emerald-600">"{currentParam.name}"</strong> parameter, configure the survey responses and analysis details.
                                                                        Auditors and team members can open these direct links during review.
                                                                    </p>
                                                                </div>

                                                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                                                    <div className="space-y-1.5">
                                                                        <label className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] ml-1">Google Sheet Link</label>
                                                                        <input 
                                                                            type="url"
                                                                            value={sub.googleSheetLink || ''}
                                                                            onChange={(e) => updateSubsection(currentParam.id, sub.id, 'googleSheetLink', e.target.value)}
                                                                            placeholder="https://docs.google.com/spreadsheets/d/..."
                                                                            className="w-full bg-[var(--bg-card)] border border-[var(--border)] focus:border-emerald-500 rounded-xl px-4 py-2.5 text-xs font-black text-[var(--text-main)] outline-none transition-all"
                                                                        />
                                                                    </div>
                                                                    <div className="space-y-1.5">
                                                                        <label className="text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] ml-1">Google Form Link</label>
                                                                        <input 
                                                                            type="url"
                                                                            value={sub.googleFormLink || ''}
                                                                            onChange={(e) => updateSubsection(currentParam.id, sub.id, 'googleFormLink', e.target.value)}
                                                                            placeholder="https://docs.google.com/forms/d/..."
                                                                            className="w-full bg-[var(--bg-card)] border border-[var(--border)] focus:border-emerald-500 rounded-xl px-4 py-2.5 text-xs font-black text-[var(--text-main)] outline-none transition-all"
                                                                        />
                                                                    </div>
                                                                </div>

                                                                <div className="flex justify-end pt-4 border-t border-[var(--border)]">
                                                                    <button 
                                                                        onClick={() => handleSaveProgress(currentParam.name)}
                                                                        disabled={isSaving}
                                                                        className="flex items-center gap-2 px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-black text-xs uppercase tracking-widest shadow-lg shadow-blue-500/20 disabled:opacity-50 transition-all"
                                                                    >
                                                                        {isSaving ? <Clock className="animate-spin" size={14} /> : <Save size={14} />} Save Audit Configuration
                                                                    </button>
                                                                </div>
                                                            </div>
                                                        );
                                                    } else if (currentParam.id === 'p4' || currentParam.name === 'Team Engagement index') {
                                                        return (
                                                            <div className="flex-1 flex flex-col justify-between pt-4 space-y-4 overflow-hidden">
                                                                <div className="flex items-center justify-between border-y border-[var(--border)] py-2">
                                                                    <div className="flex items-center gap-4">
                                                                        <span className="text-[10px] font-black uppercase text-purple-600">Checklist Builder</span>
                                                                        <div className="flex items-center gap-2">
                                                                            <label className="text-[9px] font-black uppercase text-[var(--text-muted)]">Survey Level:</label>
                                                                            <select 
                                                                                value={sub.surveyLevel || 'public'}
                                                                                onChange={(e) => updateSubsection(currentParam.id, sub.id, 'surveyLevel', e.target.value)}
                                                                                className="bg-[var(--bg-card)] border border-[var(--border)] rounded px-2 py-1 text-[10px] font-black outline-none focus:border-purple-500"
                                                                            >
                                                                                <option value="public">Public</option>
                                                                                <option value="anonymous">Anonymous</option>
                                                                            </select>
                                                                        </div>
                                                                    </div>

                                                                    <div className="flex items-center gap-2">
                                                                        <button 
                                                                            onClick={() => exportTeamEngagementTemplate(sub)}
                                                                            className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-500 text-white rounded-lg font-black text-[9px] uppercase shadow-md hover:bg-indigo-600 transition-all"
                                                                        >
                                                                            <FileDown size={12} /> Export Format
                                                                        </button>
                                                                        <label className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 text-white rounded-lg font-black text-[9px] uppercase shadow-md cursor-pointer hover:bg-emerald-700 transition-all">
                                                                            <FileUp size={12} /> Import Filled
                                                                            <input type="file" className="hidden" accept=".xlsx, .xls" onChange={(e) => importTeamEngagementData(currentParam.id, sub.id, e)} />
                                                                        </label>
                                                                        <button 
                                                                            onClick={() => handleSaveProgress(currentParam.name)}
                                                                            disabled={isSaving}
                                                                            className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-black text-[9px] uppercase shadow-md disabled:opacity-50 transition-all"
                                                                        >
                                                                            {isSaving ? <Clock className="animate-spin" size={12} /> : <Save size={12} />} Save Audit Setup
                                                                        </button>
                                                                    </div>
                                                                </div>

                                                                <div className="text-[10px] font-bold text-[var(--text-muted)] bg-[var(--bg-card)] border border-[var(--border)] px-4 py-2.5 rounded-xl">
                                                                    {sub.surveyLevel === 'anonymous' 
                                                                        ? "🔒 Anonymous Survey Mode Enabled: Only survey responses will be saved. Identifiers (name, email) are kept hidden to protect identity."
                                                                        : "👤 Public Survey Mode Enabled: Survey respondent's name and email will be saved along with their responses for permanent accountability."
                                                                    }
                                                                </div>

                                                                <div className="flex-1 overflow-y-auto pr-1 space-y-2 custom-scrollbar">
                                                                    <table className="w-full text-left border-collapse">
                                                                        <thead>
                                                                            <tr className="text-[9px] font-black uppercase text-[var(--text-muted)] border-b border-[var(--border)]">
                                                                                <th className="pb-2 w-10 text-center">S.No</th>
                                                                                <th className="pb-2">Question</th>
                                                                                <th className="pb-2 w-24">Minimum Marks</th>
                                                                                <th className="pb-2 w-32">Review / Value</th>
                                                                                <th className="pb-2 w-10"></th>
                                                                            </tr>
                                                                        </thead>
                                                                        <tbody>
                                                                            {(sub.teamEngagementChecklist || []).map((item, rIdx) => (
                                                                                <tr key={rIdx} className="border-b border-[var(--border)] last:border-0 group">
                                                                                    <td className="py-2 text-center text-[10px] font-bold">{item.sno}</td>
                                                                                    <td className="py-2">
                                                                                        <input 
                                                                                            value={item.question}
                                                                                            onChange={(e) => updateTeamEngagementRow(currentParam.id, sub.id, rIdx, 'question', e.target.value)}
                                                                                            className="w-full bg-transparent border-none text-[10px] font-black p-0 focus:ring-0"
                                                                                            placeholder="Define Question..."
                                                                                        />
                                                                                    </td>
                                                                                    <td className="py-2">
                                                                                        <input 
                                                                                            type="number"
                                                                                            value={item.min_marks}
                                                                                            onChange={(e) => updateTeamEngagementRow(currentParam.id, sub.id, rIdx, 'min_marks', parseFloat(e.target.value) || 0)}
                                                                                            className="w-16 bg-[var(--bg-card)] border border-[var(--border)] rounded p-1 text-[10px] font-black"
                                                                                        />
                                                                                    </td>
                                                                                    <td className="py-2">
                                                                                        <input 
                                                                                            value={item.review}
                                                                                            onChange={(e) => updateTeamEngagementRow(currentParam.id, sub.id, rIdx, 'review', e.target.value)}
                                                                                            className="w-full bg-transparent border-none text-[9px] font-bold p-0 focus:ring-0 opacity-50 group-hover:opacity-100"
                                                                                            placeholder="Review notes..."
                                                                                        />
                                                                                    </td>
                                                                                    <td className="py-2 text-center">
                                                                                        <button onClick={() => removeTeamEngagementRow(currentParam.id, sub.id, rIdx)} className="text-red-500 opacity-0 group-hover:opacity-100"><X size={12}/></button>
                                                                                    </td>
                                                                                </tr>
                                                                            ))}
                                                                        </tbody>
                                                                    </table>
                                                                    <button 
                                                                        onClick={() => addTeamEngagementRow(currentParam.id, sub.id)}
                                                                        className="w-full py-2 border-2 border-dashed border-[var(--border)] rounded-xl text-[10px] font-black text-[var(--text-muted)] hover:text-blue-500 hover:border-blue-500/30 transition-all flex items-center justify-center gap-2"
                                                                    >
                                                                        <Plus size={12} /> Add New Question
                                                                    </button>
                                                                </div>
                                                            </div>
                                                        );
                                                    } else if (isBudgetAdherence) {
                                                         return (
                                                             <div className="flex-1 flex flex-col justify-between pt-4 space-y-4 overflow-hidden">
                                                                 <div className="flex items-center justify-between border-y border-[var(--border)] py-2">
                                                                     <span className="text-[10px] font-black uppercase text-purple-600">Budget Cost Adherence Setup</span>
                                                                     <div className="flex items-center gap-2">
                                                                         <button 
                                                                             onClick={() => exportBudgetAdherenceTemplate(sub)}
                                                                             className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-500 text-white rounded-lg font-black text-[9px] uppercase shadow-md hover:bg-indigo-600 transition-all"
                                                                         >
                                                                             <FileDown size={12} /> Export Format
                                                                         </button>
                                                                         <label className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 text-white rounded-lg font-black text-[9px] uppercase shadow-md cursor-pointer hover:bg-emerald-700 transition-all">
                                                                             <FileUp size={12} /> Import Filled
                                                                             <input type="file" className="hidden" accept=".xlsx, .xls" onChange={(e) => importBudgetAdherenceData(currentParam.id, sub.id, e)} />
                                                                         </label>
                                                                         <button 
                                                                             onClick={() => handleSaveProgress(currentParam.name)}
                                                                             disabled={isSaving}
                                                                             className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-black text-[9px] uppercase shadow-md disabled:opacity-50 transition-all"
                                                                         >
                                                                             {isSaving ? <Clock className="animate-spin" size={12} /> : <Save size={12} />} Save Audit Setup
                                                                         </button>
                                                                     </div>
                                                                 </div>

                                                                 <div className="flex-1 overflow-x-auto overflow-y-auto pr-1 space-y-2 custom-scrollbar">
                                                                     <table className="min-w-[1200px] w-full text-left border-collapse">
                                                                         <thead>
                                                                             <tr className="text-[9px] font-black uppercase text-[var(--text-muted)] border-b border-[var(--border)]">
                                                                                 <th className="pb-2 w-10 text-center">S.No</th>
                                                                                 <th className="pb-2 w-40">Particulars</th>
                                                                                 <th className="pb-2 w-36">Particulars Head</th>
                                                                                 <th className="pb-2 w-36">Head Subhead</th>
                                                                                 <th className="pb-2 w-20">Rate</th>
                                                                                 <th className="pb-2 w-20">Target</th>
                                                                                 <th className="pb-2 w-20">Actual</th>
                                                                                 <th className="pb-2 w-20">Gap</th>
                                                                                 <th className="pb-2 w-28">Raised By</th>
                                                                                 <th className="pb-2 w-28">Raised To</th>
                                                                                 <th className="pb-2 w-40">Reason</th>
                                                                                 <th className="pb-2 w-10"></th>
                                                                             </tr>
                                                                         </thead>
                                                                         <tbody>
                                                                             {(sub.budgetAdherenceChecklist || []).map((item, rIdx) => (
                                                                                 <tr key={rIdx} className="border-b border-[var(--border)] last:border-0 group">
                                                                                     <td className="py-2 text-center text-[10px] font-bold">{item.sno}</td>
                                                                                     <td className="py-2">
                                                                                         <input 
                                                                                             value={item.particulars || ''}
                                                                                             onChange={(e) => updateBudgetAdherenceRow(currentParam.id, sub.id, rIdx, 'particulars', e.target.value)}
                                                                                             className="w-full bg-transparent border-none text-[10px] font-black p-0 focus:ring-0"
                                                                                             placeholder="Particulars..."
                                                                                         />
                                                                                     </td>
                                                                                     <td className="py-2">
                                                                                         <input 
                                                                                             value={item.head || ''}
                                                                                             onChange={(e) => updateBudgetAdherenceRow(currentParam.id, sub.id, rIdx, 'head', e.target.value)}
                                                                                             className="w-full bg-transparent border-none text-[10px] font-black p-0 focus:ring-0"
                                                                                             placeholder="Particulars Head..."
                                                                                         />
                                                                                     </td>
                                                                                     <td className="py-2">
                                                                                         <input 
                                                                                             value={item.subhead || ''}
                                                                                             onChange={(e) => updateBudgetAdherenceRow(currentParam.id, sub.id, rIdx, 'subhead', e.target.value)}
                                                                                             className="w-full bg-transparent border-none text-[10px] font-black p-0 focus:ring-0"
                                                                                             placeholder="Head Subhead..."
                                                                                         />
                                                                                     </td>
                                                                                     <td className="py-2">
                                                                                         <input 
                                                                                             type="number"
                                                                                             value={item.rate}
                                                                                             onChange={(e) => updateBudgetAdherenceRow(currentParam.id, sub.id, rIdx, 'rate', parseFloat(e.target.value) || 0)}
                                                                                             className="w-16 bg-[var(--bg-card)] border border-[var(--border)] rounded p-1 text-[10px] font-black"
                                                                                         />
                                                                                     </td>
                                                                                     <td className="py-2">
                                                                                         <input 
                                                                                             type="number"
                                                                                             value={item.target}
                                                                                             onChange={(e) => updateBudgetAdherenceRow(currentParam.id, sub.id, rIdx, 'target', parseFloat(e.target.value) || 0)}
                                                                                             className="w-16 bg-[var(--bg-card)] border border-[var(--border)] rounded p-1 text-[10px] font-black"
                                                                                         />
                                                                                     </td>
                                                                                     <td className="py-2">
                                                                                         <input 
                                                                                             type="number"
                                                                                             value={item.actual}
                                                                                             onChange={(e) => updateBudgetAdherenceRow(currentParam.id, sub.id, rIdx, 'actual', parseFloat(e.target.value) || 0)}
                                                                                             className="w-16 bg-[var(--bg-card)] border border-[var(--border)] rounded p-1 text-[10px] font-black"
                                                                                         />
                                                                                     </td>
                                                                                     <td className="py-2 text-[10px] font-bold">
                                                                                         <span className={item.gap < 0 ? 'text-red-500' : item.gap > 0 ? 'text-amber-500' : 'text-green-500'}>
                                                                                             {item.gap}
                                                                                         </span>
                                                                                     </td>
                                                                                     <td className="py-2">
                                                                                         <input 
                                                                                             value={item.raised_by || ''}
                                                                                             onChange={(e) => updateBudgetAdherenceRow(currentParam.id, sub.id, rIdx, 'raised_by', e.target.value)}
                                                                                             className="w-full bg-transparent border-none text-[10px] p-0 focus:ring-0"
                                                                                             placeholder="Name..."
                                                                                         />
                                                                                     </td>
                                                                                     <td className="py-2">
                                                                                         <input 
                                                                                             value={item.raised_to || ''}
                                                                                             onChange={(e) => updateBudgetAdherenceRow(currentParam.id, sub.id, rIdx, 'raised_to', e.target.value)}
                                                                                             className="w-full bg-transparent border-none text-[10px] p-0 focus:ring-0"
                                                                                             placeholder="Name..."
                                                                                         />
                                                                                     </td>
                                                                                     <td className="py-2">
                                                                                         <input 
                                                                                             value={item.reason || ''}
                                                                                             onChange={(e) => updateBudgetAdherenceRow(currentParam.id, sub.id, rIdx, 'reason', e.target.value)}
                                                                                             className="w-full bg-transparent border-none text-[9px] font-bold p-0 focus:ring-0 opacity-50 group-hover:opacity-100"
                                                                                             placeholder="Reason..."
                                                                                         />
                                                                                     </td>
                                                                                     <td className="py-2 text-center">
                                                                                         <button onClick={() => removeBudgetAdherenceRow(currentParam.id, sub.id, rIdx)} className="text-red-500 opacity-0 group-hover:opacity-100"><X size={12}/></button>
                                                                                     </td>
                                                                                 </tr>
                                                                             ))}
                                                                         </tbody>
                                                                     </table>
                                                                     <button 
                                                                         onClick={() => addBudgetAdherenceRow(currentParam.id, sub.id)}
                                                                         className="min-w-[1200px] w-full py-2 border-2 border-dashed border-[var(--border)] rounded-xl text-[10px] font-black text-[var(--text-muted)] hover:text-blue-500 hover:border-blue-500/30 transition-all flex items-center justify-center gap-2"
                                                                     >
                                                                         <Plus size={12} /> Add New Particulars Row
                                                                     </button>
                                                                 </div>
                                                             </div>
                                                         );
                                                    } else {
                                                        return (
                                                            <div className="flex-1 flex flex-col justify-between pt-6">
                                                                <div className="p-6 bg-blue-500/5 rounded-2xl border border-blue-500/10 space-y-4">
                                                                    <div className="flex items-center gap-2 text-blue-500">
                                                                        <ClipboardCheck size={20} />
                                                                        <h4 className="text-sm font-black uppercase tracking-wider">Direct Score Verification Setup</h4>
                                                                    </div>
                                                                    <p className="text-xs font-bold text-[var(--text-muted)] leading-relaxed">
                                                                        For the <strong className="text-blue-500">"{currentParam.name}"</strong> parameter, there is no checklist required.
                                                                        Verification is performed by directly evaluating and entering the audited achievement value along with verifying evidence and providing remarks during the audit step.
                                                                    </p>
                                                                    <div className="text-[10px] font-black uppercase tracking-wider text-amber-500 bg-amber-500/10 px-3 py-2 rounded-lg inline-block">
                                                                        Target type: {sub.isPercentage ? "Percentage (%)" : "Numerical Value (#)"}
                                                                    </div>
                                                                </div>

                                                                <div className="flex justify-end pt-4 border-t border-[var(--border)]">
                                                                    <button 
                                                                        onClick={() => handleSaveProgress(currentParam.name)}
                                                                        disabled={isSaving}
                                                                        className="flex items-center gap-2 px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-black text-xs uppercase tracking-widest shadow-lg shadow-blue-500/20 disabled:opacity-50 transition-all"
                                                                    >
                                                                        {isSaving ? <Clock className="animate-spin" size={14} /> : <Save size={14} />} Save Audit Configuration
                                                                    </button>
                                                                </div>
                                                            </div>
                                                        );
                                                    }
                                                })()}
                                            </div>
                                        );
                                    })()}
                                </>
                            ) : (
                                <div className="flex flex-col items-center justify-center h-full space-y-4 opacity-40">
                                    <ClipboardCheck size={48} className="text-[var(--text-muted)]" />
                                    <p className="text-sm font-black text-[var(--text-muted)] text-center">Select a subsection from the left <br/> to enable and build its Audit Checklist.</p>
                                </div>
                            )}
                        </div>
                    </div>
                  </div>
                )}
              </motion.div>
            </AnimatePresence>
          </div>

          {/* Compact Navigation Footer */}
          <div className="p-4 bg-[var(--input-bg)]/20 border-t border-[var(--border)] flex justify-between items-center">
            <button
              onClick={() => {
                if (currentStep > 1) setCurrentStep(currentStep - 1);
                else if (activeParamIndex > 0) { setActiveParamIndex(activeParamIndex - 1); setCurrentStep(4); }
              }}
              disabled={currentStep === 1 && activeParamIndex === 0}
              className="px-6 py-2.5 bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-main)] rounded-xl font-black text-[10px] uppercase tracking-widest hover:bg-[var(--input-bg)] transition-all disabled:opacity-20"
            >
              Back
            </button>

            <div className="flex items-center gap-3">
              {currentStep === 4 && (
                <button
                  onClick={() => handleSaveProgress(currentParam.name)}
                  disabled={isSaving}
                  className="px-6 py-2.5 bg-blue-600/10 hover:bg-blue-600/20 text-blue-500 border border-blue-500/20 rounded-xl font-black text-[10px] uppercase tracking-widest transition-all active:scale-95 disabled:opacity-50 flex items-center gap-2"
                >
                  {isSaving ? <Clock className="animate-spin" size={12} /> : <Save size={12} />}
                  Save Progress
                </button>
              )}

              {currentStep === 4 && activeParamIndex === parameters.length - 1 ? (
                <button
                  onClick={handleSave}
                  disabled={isSaving}
                  className="px-8 py-2.5 bg-green-600 hover:bg-green-700 text-white rounded-xl font-black text-[10px] uppercase tracking-widest shadow-lg shadow-green-500/20 transition-all active:scale-95 disabled:opacity-50 flex items-center gap-2"
                >
                  {isSaving ? <Clock className="animate-spin" size={12} /> : <Save size={12} />}
                  Finalize ORM Setup
                </button>
              ) : (
                <button
                  onClick={() => {
                    if (currentStep < 4) setCurrentStep(currentStep + 1);
                    else { setActiveParamIndex(activeParamIndex + 1); setCurrentStep(1); }
                  }}
                  className="px-10 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-black text-[10px] uppercase tracking-widest shadow-lg shadow-blue-500/20 transition-all active:scale-95 flex items-center gap-2"
                >
                  Next Stage <ArrowRight size={14} />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      <style dangerouslySetInnerHTML={{ __html: `
        .custom-scrollbar::-webkit-scrollbar { width: 4px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: var(--border); border-radius: 10px; }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover { background: #3b82f6; }
      `}} />

      {/* Warning Toast */}
      {parameters.reduce((acc, p) => acc + (parseFloat(p.weightage) || 0), 0) !== 100 && (
        <div className="fixed bottom-6 right-6 bg-orange-600 text-white px-6 py-3 rounded-2xl shadow-xl flex items-center gap-3 border-2 border-white/10 z-[60]">
          <AlertCircle size={18} />
          <span className="text-[10px] font-black uppercase tracking-widest">Global Weightage: {parameters.reduce((acc, p) => acc + (parseFloat(p.weightage) || 0), 0)}% (Goal: 100%)</span>
        </div>
      )}
    </div>
  );
};

export default ORMSetup;
