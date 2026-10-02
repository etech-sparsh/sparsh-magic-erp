import React, { useMemo, useState } from 'react';
import { Search, ChevronLeft, ChevronRight, ChevronsUpDown, ArrowUp, ArrowDown, Inbox } from 'lucide-react';

/**
 * Reusable enterprise data-table for TPMS.
 *
 * props:
 *  columns : [{ key, header, render?(row), sortable?, align?, className? }]
 *  rows    : array of objects
 *  pageSize: rows per page (default 8)
 *  searchKeys : keys to match the search box against (default: all string cols)
 *  toolbar : optional React node rendered on the right of the search bar
 *  title, subtitle : optional header text
 */
const DataTable = ({ columns, rows, pageSize = 8, searchKeys, toolbar, title, subtitle }) => {
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState({ key: null, dir: 'asc' });

  const keys = searchKeys || columns.map((c) => c.key);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) => keys.some((k) => String(r[k] ?? '').toLowerCase().includes(q)));
  }, [rows, query, keys]);

  const sorted = useMemo(() => {
    if (!sort.key) return filtered;
    const arr = [...filtered].sort((a, b) => {
      const av = a[sort.key], bv = b[sort.key];
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === 'number' && typeof bv === 'number') return av - bv;
      return String(av).localeCompare(String(bv));
    });
    return sort.dir === 'asc' ? arr : arr.reverse();
  }, [filtered, sort]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const current = Math.min(page, totalPages);
  const pageRows = sorted.slice((current - 1) * pageSize, current * pageSize);

  const toggleSort = (key) =>
    setSort((s) => (s.key !== key ? { key, dir: 'asc' } : { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }));

  const onSearch = (v) => { setQuery(v); setPage(1); };

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm overflow-hidden">
      {/* Header / toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 border-b border-[var(--border)]">
          <div className="min-w-0">
            {title && <h3 className="text-[14px] font-extrabold tracking-tight">{title}</h3>}
            {subtitle && <p className="text-[12px] text-[var(--text-muted)] mt-0.5">{subtitle}</p>}
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input
                value={query}
                onChange={(e) => onSearch(e.target.value)}
                placeholder="Search..."
                className="pl-9 pr-3 py-2 w-56 bg-[var(--input-bg)] border border-[var(--input-border)] rounded-lg outline-none focus:border-[var(--accent-indigo)] text-[13px] font-medium placeholder:text-[var(--text-muted)]"
              />
            </div>
            {toolbar}
          </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto no-scrollbar">
        <table className="w-full min-w-[640px]">
          <thead>
            <tr className="bg-[var(--table-header-bg)]">
              {columns.map((c) => (
                <th
                  key={c.key}
                  onClick={() => c.sortable && toggleSort(c.key)}
                  className={`px-5 py-3 text-[10px] font-bold uppercase tracking-widest text-[var(--text-muted)]
                    ${c.align === 'right' ? 'text-right' : c.align === 'center' ? 'text-center' : 'text-left'}
                    ${c.sortable ? 'cursor-pointer select-none hover:text-[var(--text-main)]' : ''}`}
                >
                  <span className={`inline-flex items-center gap-1 ${c.align === 'right' ? 'flex-row-reverse' : ''}`}>
                    {c.header}
                    {c.sortable && (
                      sort.key === c.key
                        ? (sort.dir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />)
                        : <ChevronsUpDown size={12} className="opacity-40" />
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row, i) => (
              <tr key={row.id ?? i} className="border-t border-[var(--border)] hover:bg-[var(--table-hover)] transition-colors">
                {columns.map((c) => (
                  <td key={c.key}
                      className={`px-5 py-3.5 text-[12.5px] align-middle
                        ${c.align === 'right' ? 'text-right' : c.align === 'center' ? 'text-center' : 'text-left'} ${c.className || ''}`}>
                    {c.render ? c.render(row) : row[c.key]}
                  </td>
                ))}
              </tr>
            ))}
            {pageRows.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-5 py-16 text-center">
                  <div className="flex flex-col items-center gap-2 text-[var(--text-muted)]">
                    <Inbox size={28} />
                    <span className="text-[13px] font-bold">No results found</span>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 border-t border-[var(--border)]">
        <span className="text-[12px] font-medium text-[var(--text-muted)]">
          Showing <b className="text-[var(--text-main)]">{sorted.length === 0 ? 0 : (current - 1) * pageSize + 1}</b>
          –<b className="text-[var(--text-main)]">{Math.min(current * pageSize, sorted.length)}</b> of{' '}
          <b className="text-[var(--text-main)]">{sorted.length}</b>
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={current === 1}
            className="p-1.5 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--input-bg)] disabled:opacity-40 disabled:pointer-events-none"
          >
            <ChevronLeft size={16} />
          </button>
          {Array.from({ length: totalPages }, (_, i) => i + 1)
            .filter((p) => p === 1 || p === totalPages || Math.abs(p - current) <= 1)
            .map((p, idx, arr) => (
              <React.Fragment key={p}>
                {idx > 0 && p - arr[idx - 1] > 1 && <span className="px-1 text-[var(--text-muted)]">…</span>}
                <button
                  onClick={() => setPage(p)}
                  className={`min-w-[32px] h-8 px-2 rounded-lg text-[12.5px] font-bold transition-all
                    ${p === current
                      ? 'bg-[var(--sidebar-active-bg)] text-[var(--sidebar-active-text)]'
                      : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)]'}`}
                >
                  {p}
                </button>
              </React.Fragment>
            ))}
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={current === totalPages}
            className="p-1.5 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--input-bg)] disabled:opacity-40 disabled:pointer-events-none"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>
    </div>
  );
};

export default DataTable;
