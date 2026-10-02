import React, { useMemo, useRef, useState } from 'react';
import {  AnimatePresence , motion } from 'framer-motion';
import { X, Upload, FileSpreadsheet, Download, CheckCircle2, AlertTriangle, CopyX, Loader2, ArrowLeft } from 'lucide-react';
import * as XLSX from 'xlsx';
import { createHoliday } from '../../services/holidayApi';

// Columns the uploaded file must contain (header match is case-insensitive / trimmed).
const REQUIRED_COLUMNS = ['Holiday Name', 'Date', 'Holiday Type', 'Description'];
const HOLIDAY_TYPES = ['National', 'Festival', 'Company', 'Optional'];
const ACCEPTED_EXT = ['xlsx', 'xls', 'csv'];

const pad = (n) => String(n).padStart(2, '0');
const toKey = (y, m, d) => `${y}-${pad(m)}-${pad(d)}`;
const dupKey = (date, name) => `${date}|${(name || '').trim().toLowerCase()}`;

// Normalise a cell into an ISO "YYYY-MM-DD" date string, or null when unparseable.
// Handles Excel Date objects (cellDates), Excel serial numbers, ISO, and common
// day-first / textual formats. Purely client-side — mirrors how the app stores dates.
const parseDate = (value) => {
  if (value === null || value === undefined || value === '') return null;
  if (value instanceof Date && !isNaN(value.getTime())) {
    return toKey(value.getFullYear(), value.getMonth() + 1, value.getDate());
  }
  if (typeof value === 'number' && isFinite(value)) {
    const ms = Date.UTC(1899, 11, 30) + Math.round(value) * 86400000;
    const d = new Date(ms);
    return toKey(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate());
  }
  const s = String(value).trim();
  if (!s) return null;
  let m = s.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/); // ISO YYYY-MM-DD
  if (m) return toKey(+m[1], +m[2], +m[3]);
  m = s.match(/^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$/); // DD/MM/YYYY (day-first)
  if (m) {
    let d = +m[1]; let mo = +m[2];
    if (mo > 12 && d <= 12) { const t = d; d = mo; mo = t; } // tolerate MM/DD when unambiguous
    if (mo >= 1 && mo <= 12 && d >= 1 && d <= 31) return toKey(+m[3], mo, d);
  }
  const parsed = new Date(s); // e.g. "15 August 2026", "Aug 15, 2026"
  if (!isNaN(parsed.getTime())) return toKey(parsed.getFullYear(), parsed.getMonth() + 1, parsed.getDate());
  return null;
};

const isValidKey = (key) => {
  if (!key) return false;
  const d = new Date(`${key}T00:00:00`);
  return !isNaN(d.getTime());
};

// Bulk-import holidays from an .xlsx / .csv file. Parses & validates entirely on the
// client, previews every row, then imports the valid, non-duplicate rows through the
// existing createHoliday API (which itself rejects duplicates as a backstop).
const HolidayImportModal = ({ isOpen, onClose, existingHolidays = [], onImported }) => {
  const inputRef = useRef(null);

  const [fileName, setFileName] = useState('');
  const [parsing, setParsing] = useState(false);
  const [fileError, setFileError] = useState('');
  const [rows, setRows] = useState(null); // parsed+validated rows, or null before upload
  const [importing, setImporting] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [result, setResult] = useState(null); // { imported, skipped, errors: [] }

  // Duplicate lookup for holidays that already exist in the system.
  const existingKeys = useMemo(() => {
    const set = new Set();
    (existingHolidays || []).forEach(h => set.add(dupKey(h.holiday_date, h.holiday_name)));
    return set;
  }, [existingHolidays]);

  const reset = () => {
    setFileName(''); setFileError(''); setRows(null);
    setImporting(false); setProgress({ done: 0, total: 0 }); setResult(null);
    if (inputRef.current) inputRef.current.value = '';
  };

  const handleClose = () => { reset(); onClose?.(); };

  const downloadTemplate = () => {
    const sample = [
      { 'Holiday Name': 'Republic Day', Date: '2026-01-26', 'Holiday Type': 'National', Description: 'National holiday' },
      { 'Holiday Name': 'Diwali', Date: '2026-11-08', 'Holiday Type': 'Festival', Description: 'Festival of lights' },
    ];
    const ws = XLSX.utils.json_to_sheet(sample, { header: REQUIRED_COLUMNS });
    ws['!cols'] = [{ wch: 24 }, { wch: 14 }, { wch: 16 }, { wch: 36 }];
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Holidays');
    XLSX.writeFile(wb, 'holiday_import_template.xlsx');
  };

  const handleFile = (file) => {
    if (!file) return;
    reset();
    const ext = (file.name.split('.').pop() || '').toLowerCase();
    setFileName(file.name);
    if (!ACCEPTED_EXT.includes(ext)) {
      setFileError('Unsupported file format. Please upload a .xlsx or .csv file.');
      return;
    }
    setParsing(true);
    const reader = new FileReader();
    reader.onerror = () => { setParsing(false); setFileError('Could not read the file. Please try again.'); };
    reader.onload = (e) => {
      try {
        const data = new Uint8Array(e.target.result);
        const wb = XLSX.read(data, { type: 'array', cellDates: true });
        const ws = wb.Sheets[wb.SheetNames[0]];
        if (!ws) { setFileError('The file has no readable sheet.'); setParsing(false); return; }

        const grid = XLSX.utils.sheet_to_json(ws, { header: 1, raw: true, blankrows: false, defval: '' });
        if (!grid.length) { setFileError('The file is empty.'); setParsing(false); return; }

        const header = grid[0].map(h => String(h || '').trim());
        const idx = {};
        header.forEach((h, i) => { idx[h.toLowerCase()] = i; });
        const missing = REQUIRED_COLUMNS.filter(c => !(c.toLowerCase() in idx));
        if (missing.length) {
          setFileError(`Missing required column${missing.length > 1 ? 's' : ''}: ${missing.join(', ')}.`);
          setParsing(false);
          return;
        }

        const col = (name) => idx[name.toLowerCase()];
        const nameI = col('Holiday Name'); const dateI = col('Date');
        const typeI = col('Holiday Type'); const descI = col('Description');

        const seen = new Set();
        const parsed = [];
        for (let r = 1; r < grid.length; r++) {
          const raw = grid[r] || [];
          const rawName = raw[nameI]; const rawDate = raw[dateI];
          const rawType = raw[typeI]; const rawDesc = raw[descI];
          const name = String(rawName ?? '').trim();
          const description = String(rawDesc ?? '').trim();
          const typeText = String(rawType ?? '').trim();

          // Skip fully blank rows silently.
          if (!name && (rawDate === '' || rawDate == null) && !typeText && !description) continue;

          const dateKey = parseDate(rawDate);
          const canonicalType = HOLIDAY_TYPES.find(t => t.toLowerCase() === typeText.toLowerCase());

          const errors = [];
          if (!name) errors.push('Holiday Name is required');
          if (!dateKey || !isValidKey(dateKey)) errors.push('Date is missing or invalid');
          if (typeText && !canonicalType) errors.push(`Invalid Holiday Type "${typeText}"`);

          const row = {
            excelRow: r + 1,
            holiday_name: name,
            holiday_date: dateKey || String(rawDate ?? '').trim(),
            holiday_type: canonicalType || (typeText ? typeText : 'Company'),
            description,
            status: 'active',
          };

          if (errors.length) { row.rowStatus = 'error'; row.message = errors.join('; '); }
          else {
            const k = dupKey(dateKey, name);
            if (existingKeys.has(k)) { row.rowStatus = 'duplicate'; row.message = 'Already exists'; }
            else if (seen.has(k)) { row.rowStatus = 'duplicate'; row.message = 'Duplicate row in file'; }
            else { row.rowStatus = 'ready'; seen.add(k); }
          }
          parsed.push(row);
        }

        if (!parsed.length) { setFileError('No data rows found in the file.'); setParsing(false); return; }
        setRows(parsed);
        setParsing(false);
      } catch (err) {
        setParsing(false);
        setFileError('Could not parse the file. Ensure it is a valid Excel or CSV file.');
      }
    };
    reader.readAsArrayBuffer(file);
  };

  const counts = useMemo(() => {
    const c = { ready: 0, duplicate: 0, error: 0 };
    (rows || []).forEach(r => { c[r.rowStatus] = (c[r.rowStatus] || 0) + 1; });
    return c;
  }, [rows]);

  const runImport = async () => {
    const ready = (rows || []).filter(r => r.rowStatus === 'ready');
    if (!ready.length) return;
    setImporting(true);
    setProgress({ done: 0, total: ready.length });
    let imported = 0;
    let skipped = counts.duplicate;
    const errors = (rows || []).filter(r => r.rowStatus === 'error').map(r => ({ row: r.excelRow, name: r.holiday_name || '(no name)', message: r.message }));

    for (let i = 0; i < ready.length; i++) {
      const r = ready[i];
      try {
        await createHoliday({
          holiday_name: r.holiday_name,
          holiday_date: r.holiday_date,
          holiday_type: r.holiday_type,
          description: r.description,
          status: 'active',
        });
        imported += 1;
      } catch (err) {
        const st = err.response?.status;
        const detail = err.response?.data?.detail || 'Failed to import';
        if (st === 409) { skipped += 1; } // duplicate the backstop caught
        else { errors.push({ row: r.excelRow, name: r.holiday_name, message: detail }); }
      }
      setProgress({ done: i + 1, total: ready.length });
    }

    setImporting(false);
    setResult({ imported, skipped, errors });
    if (imported > 0) onImported?.();
  };

  if (!isOpen) return null;

  const statusBadge = (s) => {
    if (s === 'ready') return { label: 'Ready', color: 'var(--accent-green)', Icon: CheckCircle2 };
    if (s === 'duplicate') return { label: 'Skip · Duplicate', color: 'var(--accent-orange)', Icon: CopyX };
    return { label: 'Error', color: 'var(--accent-red)', Icon: AlertTriangle };
  };

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[300] flex items-center justify-center p-4">
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={handleClose}
          className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
        <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }}
          className="relative w-full max-w-2xl max-h-[90vh] flex flex-col bg-[var(--bg-card)] border border-[var(--border)] rounded-[24px] shadow-2xl overflow-hidden">
          {/* Header */}
          <div className="px-6 py-4 border-b border-[var(--border)] flex items-center gap-3 bg-[var(--accent-indigo-bg)] shrink-0">
            <div className="w-10 h-10 rounded-xl bg-[var(--accent-indigo)] text-white flex items-center justify-center shrink-0 shadow-md shadow-[var(--accent-indigo)]/20">
              <FileSpreadsheet size={20} />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-[15px] font-black text-[var(--text-main)] leading-tight">Bulk Import Holidays</h3>
              <p className="text-[10px] font-black text-[var(--accent-indigo)] uppercase tracking-widest">Excel / CSV Upload</p>
            </div>
            <button onClick={handleClose} className="p-1.5 rounded-full hover:bg-[var(--bg-card)] text-[var(--text-muted)] hover:text-[var(--text-main)] transition-colors"><X size={18} /></button>
          </div>

          <div className="p-6 overflow-y-auto">
            {/* ─── Step 1 · Upload ─── */}
            {!rows && !result && (
              <div className="space-y-4">
                <div
                  onClick={() => inputRef.current?.click()}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => { e.preventDefault(); handleFile(e.dataTransfer.files?.[0]); }}
                  className="cursor-pointer border-2 border-dashed border-[var(--border)] rounded-2xl p-10 text-center hover:border-[var(--accent-indigo)] hover:bg-[var(--input-bg)] transition-all">
                  {parsing ? (
                    <Loader2 size={30} className="mx-auto mb-3 text-[var(--accent-indigo)] animate-spin" />
                  ) : (
                    <Upload size={30} className="mx-auto mb-3 text-[var(--text-muted)]" />
                  )}
                  <p className="text-[13px] font-black text-[var(--text-main)]">{parsing ? 'Reading file…' : 'Click to upload or drag & drop'}</p>
                  <p className="text-[11px] font-bold text-[var(--text-muted)] mt-1">Excel (.xlsx) or CSV (.csv){fileName ? ` · ${fileName}` : ''}</p>
                  <input ref={inputRef} type="file" accept=".xlsx,.xls,.csv" className="hidden"
                    onChange={(e) => handleFile(e.target.files?.[0])} />
                </div>

                {fileError && (
                  <div className="flex items-start gap-2 p-3 rounded-xl bg-[var(--accent-red-bg)] border border-[var(--accent-red-border)]">
                    <AlertTriangle size={15} className="text-[var(--accent-red)] mt-0.5 shrink-0" />
                    <p className="text-[12px] font-bold text-[var(--accent-red)]">{fileError}</p>
                  </div>
                )}

                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <p className="text-[11px] font-bold text-[var(--text-muted)]">
                    Required columns: <span className="text-[var(--text-main)]">{REQUIRED_COLUMNS.join(', ')}</span>
                  </p>
                  <button onClick={downloadTemplate}
                    className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-[11px] font-black uppercase tracking-widest text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] hover:opacity-90 transition-all">
                    <Download size={14} /> Template
                  </button>
                </div>
              </div>
            )}

            {/* ─── Step 2 · Preview ─── */}
            {rows && !result && (
              <div className="space-y-4">
                <div className="grid grid-cols-3 gap-3">
                  {[
                    ['Ready', counts.ready, 'var(--accent-green)'],
                    ['Duplicates', counts.duplicate, 'var(--accent-orange)'],
                    ['Errors', counts.error, 'var(--accent-red)'],
                  ].map(([label, val, color]) => (
                    <div key={label} className="bg-[var(--input-bg)] rounded-xl py-3 text-center">
                      <p className="text-[20px] font-black" style={{ color }}>{val}</p>
                      <p className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest">{label}</p>
                    </div>
                  ))}
                </div>

                <div className="border border-[var(--border)] rounded-2xl overflow-hidden">
                  <div className="max-h-[320px] overflow-auto">
                    <table className="w-full text-left">
                      <thead className="sticky top-0 bg-[var(--input-bg)] z-10">
                        <tr className="border-b border-[var(--border)]">
                          {['#', 'Holiday', 'Date', 'Type', 'Status'].map(h => (
                            <th key={h} className="px-3 py-2.5 text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest whitespace-nowrap">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((r, i) => {
                          const b = statusBadge(r.rowStatus);
                          return (
                            <tr key={i} className="border-b border-[var(--border)] last:border-0">
                              <td className="px-3 py-2.5 text-[11px] font-bold text-[var(--text-muted)]">{r.excelRow}</td>
                              <td className="px-3 py-2.5">
                                <p className="text-[12px] font-bold text-[var(--text-main)]">{r.holiday_name || <span className="text-[var(--text-muted)] italic">— missing —</span>}</p>
                                {r.description && <p className="text-[10px] text-[var(--text-muted)] truncate max-w-[220px]">{r.description}</p>}
                              </td>
                              <td className="px-3 py-2.5 text-[11px] font-bold text-[var(--text-muted)] whitespace-nowrap">{r.holiday_date || '—'}</td>
                              <td className="px-3 py-2.5 text-[11px] font-bold text-[var(--text-muted)] whitespace-nowrap">{r.holiday_type}</td>
                              <td className="px-3 py-2.5 whitespace-nowrap">
                                <span className="inline-flex items-center gap-1 text-[10px] font-black" style={{ color: b.color }} title={r.message || ''}>
                                  <b.Icon size={13} /> {b.label}
                                </span>
                                {r.message && r.rowStatus === 'error' && <p className="text-[9px] font-bold text-[var(--accent-red)] opacity-80 mt-0.5 max-w-[200px]">{r.message}</p>}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="flex items-center justify-between gap-3">
                  <button onClick={reset} disabled={importing}
                    className="flex items-center gap-1.5 px-4 py-2.5 text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--text-main)] disabled:opacity-50">
                    <ArrowLeft size={14} /> Choose another file
                  </button>
                  <button onClick={runImport} disabled={importing || counts.ready === 0}
                    className="flex items-center gap-2 px-6 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-lg hover:opacity-90 disabled:opacity-50 transition-all">
                    {importing ? <><Loader2 size={14} className="animate-spin" /> Importing {progress.done}/{progress.total}</> : <><Upload size={14} /> Import {counts.ready} Holiday{counts.ready === 1 ? '' : 's'}</>}
                  </button>
                </div>
              </div>
            )}

            {/* ─── Step 3 · Results ─── */}
            {result && (
              <div className="space-y-4">
                <div className="flex flex-col items-center text-center py-2">
                  <div className="w-14 h-14 rounded-2xl bg-[var(--accent-green-bg)] flex items-center justify-center mb-3">
                    <CheckCircle2 size={26} className="text-[var(--accent-green)]" />
                  </div>
                  <h4 className="text-[15px] font-black text-[var(--text-main)]">Import Complete</h4>
                  <p className="text-[12px] font-bold text-[var(--text-muted)] mt-1">
                    {result.imported} imported · {result.skipped} skipped · {result.errors.length} failed
                  </p>
                </div>

                <div className="grid grid-cols-3 gap-3">
                  {[
                    ['Imported', result.imported, 'var(--accent-green)'],
                    ['Skipped', result.skipped, 'var(--accent-orange)'],
                    ['Failed', result.errors.length, 'var(--accent-red)'],
                  ].map(([label, val, color]) => (
                    <div key={label} className="bg-[var(--input-bg)] rounded-xl py-3 text-center">
                      <p className="text-[20px] font-black" style={{ color }}>{val}</p>
                      <p className="text-[9px] font-black text-[var(--text-muted)] uppercase tracking-widest">{label}</p>
                    </div>
                  ))}
                </div>

                {result.errors.length > 0 && (
                  <div className="border border-[var(--accent-red-border)] rounded-2xl overflow-hidden">
                    <div className="px-4 py-2 bg-[var(--accent-red-bg)] text-[10px] font-black uppercase tracking-widest text-[var(--accent-red)]">Rows not imported</div>
                    <div className="max-h-[180px] overflow-auto divide-y divide-[var(--border)]">
                      {result.errors.map((e, i) => (
                        <div key={i} className="px-4 py-2.5 flex items-start gap-2">
                          <span className="text-[10px] font-black text-[var(--text-muted)] shrink-0 mt-0.5">Row {e.row}</span>
                          <div className="min-w-0">
                            <p className="text-[12px] font-bold text-[var(--text-main)] truncate">{e.name}</p>
                            <p className="text-[11px] font-medium text-[var(--accent-red)]">{e.message}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="flex items-center justify-end gap-3">
                  <button onClick={reset} className="px-4 py-2.5 text-[11px] font-black uppercase tracking-widest text-[var(--text-muted)] hover:text-[var(--text-main)]">Import another file</button>
                  <button onClick={handleClose}
                    className="px-6 py-2.5 bg-[var(--accent-indigo)] text-white rounded-xl text-[11px] font-black uppercase tracking-widest shadow-lg hover:opacity-90 transition-all">Done</button>
                </div>
              </div>
            )}
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default HolidayImportModal;
