import React, { useCallback, useEffect, useState } from 'react';
import { BarChart3, Building2, Users2 } from 'lucide-react';
import { useHrms } from '../HrmsContext';
import HrmsPageHeader from '../common/HrmsPageHeader';
import { HrmsLoading, HrmsError } from '../common/HrmsStates';
import { getClientAnalytics, getClientCompanies } from '../../../services/hrmsApi';
import { CARD } from '../internal/internalKit';

/**
 * HRMS ▸ Client Hiring ▸ delivery analytics.
 *
 * A SEPARATE board from the internal recruitment dashboard, not a filter on it. The two
 * tracks measure different things: internal hiring measures an approval chain and a
 * probation outcome, client hiring measures delivery against a client's expectations.
 * One combined figure would be meaningless to both audiences, so the switch at the top
 * navigates between two boards rather than narrowing one.
 *
 * -- Why "whose move is it" leads --------------------------------------------------
 * The PRO-fit flow alternates between Sparsh and the client at almost every stage. A
 * plain backlog number therefore answers the wrong question: what a recruiter needs to
 * know is which pile is theirs and which they are chasing. So the two columns come
 * before the funnel, and each names the actual work rather than a status.
 */

const Tile = ({ label, value, hint, tone = 'neutral' }) => {
  const tones = {
    neutral: 'text-[var(--text-main)]',
    good: 'text-[var(--accent-green,var(--text-main))]',
    warn: 'text-[var(--accent-orange)]',
  };
  return (
    <div className={CARD}>
      <p className="text-[10.5px] font-bold uppercase tracking-widest text-[var(--text-muted)]">
        {label}
      </p>
      <p className={`text-[24px] font-bold tabular-nums mt-1 ${tones[tone]}`}>
        {value ?? '—'}
      </p>
      {hint && <p className="text-[11px] text-[var(--text-muted)] mt-0.5">{hint}</p>}
    </div>
  );
};

const WaitingColumn = ({ icon: Icon, title, total, items, tone }) => (
  <div className={CARD}>
    <div className="flex items-center gap-2">
      <Icon size={16} className="text-[var(--text-muted)]" />
      <p className="text-[13px] font-bold text-[var(--text-main)]">{title}</p>
      <span className={`ml-auto text-[18px] font-bold tabular-nums ${tone}`}>
        {total}
      </span>
    </div>
    {Object.keys(items || {}).length ? (
      <ul className="mt-2.5 space-y-1">
        {Object.entries(items).map(([label, n]) => (
          <li key={label} className="flex items-baseline justify-between gap-3
            text-[12px]">
            <span className="text-[var(--text-muted)]">{label}</span>
            <span className="tabular-nums font-semibold text-[var(--text-main)]">{n}</span>
          </li>
        ))}
      </ul>
    ) : (
      <p className="mt-2.5 text-[12px] text-[var(--text-muted)]">Nothing outstanding.</p>
    )}
  </div>
);

const ClientRecruitmentAnalytics = () => {
  const { scope, companyId, isInternal, companyName } = useHrms();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  // Sparsh staff can look at one engagement or compare them all, and comparing is the
  // more useful default -- a delivery lead wants to see which client is stuck before
  // drilling into one.
  //
  // Defaulted to true rather than to `isInternal`, which reads false on the first render
  // while the permission context is still loading and would then stick: initial state is
  // captured once, so a value that arrives later never reaches it. The toggle only
  // renders for internal staff anyway, and a client-side caller is pinned server-side
  // whatever this says.
  const [allClients, setAllClients] = useState(true);
  // The client track has its OWN company list. The shared HRMS selector lists module
  // tenants, which on an in-house system is Sparsh Magic, and it hides itself when there
  // is only one -- so on this board it offered nothing to choose and no reason why.
  const [clients, setClients] = useState([]);
  const [anyEnabled, setAnyEnabled] = useState(true);
  const [picked, setPicked] = useState('');

  const load = useCallback(async () => {
    if (!companyId && !isInternal) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      // Dropping company_id is what asks for every client. The server pins a client-side
      // caller to their own company regardless, so this cannot widen anybody's view.
      const res = await getClientAnalytics(
        allClients && isInternal
          ? {}
          : (isInternal && picked ? { company_id: picked } : scope));
      setData(res.data || null);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Could not load client hiring analytics.');
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, isInternal, allClients, picked, JSON.stringify(scope)]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    let live = true;
    getClientCompanies({})
      .then(({ data }) => {
        if (!live) return;
        const rows = data?.client_companies || [];
        setClients(rows);
        setAnyEnabled(!!data?.any_enabled);
        // Default to the first client so switching to "One client" shows something
        // rather than an empty board with a blank selector.
        setPicked((cur) => cur || (rows[0]?.id ?? ''));
      })
      .catch(() => { if (live) { setClients([]); setAnyEnabled(false); } });
    return () => { live = false; };
  }, []);

  const h = data?.headline || {};
  const o = data?.outcomes || {};
  const peak = Math.max(1, ...(data?.funnel || []).map((f) => f.value || 0));

  return (
    <div className="space-y-5">
      <HrmsPageHeader
        icon={BarChart3}
        title="Client hiring analytics"
        subtitle="Delivery against client engagements (PRO-fit). Kept separate from Sparsh Magic's own recruitment figures."
      />

      {isInternal ? (
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1.5 p-1 rounded-xl border
            border-[var(--border)] bg-[var(--input-bg)] w-fit">
            {[[true, 'All clients'], [false, 'One client']].map(([value, label]) => (
              <button key={label} type="button" onClick={() => setAllClients(value)}
                className={`px-3 py-1.5 rounded-lg text-[12px] font-bold transition-colors
                  ${allClients === value
                    ? 'bg-[var(--accent-indigo)] text-white'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-main)]'}`}>
                {label}
              </button>
            ))}
          </div>
          {!allClients && clients.length > 0 && (
            <label className="flex items-center gap-2">
              <Building2 size={14} className="text-[var(--text-muted)]" />
              <span className="text-[10px] font-bold uppercase tracking-widest
                text-[var(--text-muted)]">Client</span>
              <select value={picked} onChange={(e) => setPicked(e.target.value)}
                className="h-9 px-2.5 rounded-lg border border-[var(--border)]
                  bg-[var(--input-bg)] text-[12.5px] font-semibold
                  text-[var(--text-main)] max-w-[240px]">
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}{c.enabled ? '' : ' (module off)'}
                  </option>
                ))}
              </select>
            </label>
          )}
          {!allClients && !clients.length && (
            <span className="text-[12px] text-[var(--accent-orange)] font-semibold">
              No client company to choose yet.
            </span>
          )}
        </div>
      ) : null}

      {isInternal && !anyEnabled && (
        <p className="text-[12px] text-[var(--accent-orange)]">
          No client company has HRMS switched on, so there is nothing for this board to
          count yet. Enabling a company is what lets its people raise a requirement and
          starts their engagement.
        </p>
      )}

      {loading && <HrmsLoading label="Loading client hiring analytics…" />}
      {error && !loading && <HrmsError message={error} onRetry={load} />}

      {!loading && !error && data && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Tile label="Requisitions live" value={h.requisitions_live}
              hint={`${h.requisitions_raised ?? 0} raised, ${h.requisitions_closed ?? 0} closed`} />
            <Tile label="Candidates sourced" value={h.candidates_sourced} />
            <Tile label="Offers out" value={h.offers_out}
              hint="released, awaiting an answer" />
            <Tile label="Joined" value={h.joined} tone="good" />
          </div>

          <div>
            <p className="text-[10.5px] font-bold uppercase tracking-widest
              text-[var(--text-muted)] mb-2">
              Whose move is it
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <WaitingColumn
                icon={Building2} title="With the client"
                total={data.waiting_on_client_total}
                items={data.waiting_on_client}
                tone="text-[var(--accent-orange)]" />
              <WaitingColumn
                icon={Users2} title="With Sparsh"
                total={data.waiting_on_sparsh_total}
                items={data.waiting_on_sparsh}
                tone="text-[var(--accent-indigo)]" />
            </div>
          </div>

          <div>
            <p className="text-[10.5px] font-bold uppercase tracking-widest
              text-[var(--text-muted)] mb-2">
              Where candidates are now
            </p>
            <div className={CARD}>
              <div className="space-y-2">
                {(data.funnel || []).map((f) => (
                  <div key={f.key} className="flex items-center gap-3">
                    <span className="w-28 shrink-0 text-[12px] text-[var(--text-muted)]">
                      {f.label}
                    </span>
                    <div className="flex-1 h-2.5 rounded-full bg-[var(--input-bg)]
                      overflow-hidden">
                      <div className="h-full rounded-full bg-[var(--accent-indigo)]"
                        style={{ width: `${Math.round((f.value / peak) * 100)}%` }} />
                    </div>
                    <span className="w-8 text-right text-[12.5px] font-bold tabular-nums
                      text-[var(--text-main)]">
                      {f.value}
                    </span>
                  </div>
                ))}
              </div>
              <p className="mt-3 text-[11px] text-[var(--text-muted)]">
                Current positions, not cumulative. Somebody who has joined is counted once,
                at Joined.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Tile label="Offer acceptance"
              value={o.offer_acceptance_rate == null ? '—' : `${o.offer_acceptance_rate}%`}
              hint={`${o.offers_accepted ?? 0} accepted, ${o.offers_declined ?? 0} declined`} />
            <Tile label="CVs turned down" value={o.cv_rejected_by_client}
              hint="by the client, after sharing" />
            <Tile label="Dropped before joining" value={o.dropped_before_joining}
              tone={o.dropped_before_joining ? 'warn' : 'neutral'} />
            <Tile label="Joiners at risk" value={h.joiners_at_risk}
              hint="flagged during pre-boarding"
              tone={h.joiners_at_risk ? 'warn' : 'neutral'} />
          </div>

          {!!(data.by_client || []).length && (
            <div>
              <p className="text-[10.5px] font-bold uppercase tracking-widest
                text-[var(--text-muted)] mb-2">
                By client
              </p>
              <div className="rounded-xl border border-[var(--border)] overflow-hidden">
                <table className="w-full text-[12.5px]">
                  <thead className="bg-[var(--input-bg)] text-[var(--text-muted)]">
                    <tr>
                      {['Client', 'Requisitions', 'Candidates', 'Joined',
                        'With them', 'With us', 'Acceptance'].map((h, i) => (
                        <th key={h}
                          className={`px-3 py-2.5 text-[10.5px] font-bold uppercase
                            tracking-widest ${i ? 'text-right' : 'text-left'}`}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_client.map((c) => (
                      <tr key={c.company_id}
                        className="border-t border-[var(--border)]">
                        <td className="px-3 py-2.5">
                          <span className="font-semibold text-[var(--text-main)]">
                            {c.company_name}
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums">
                          <span className="text-[var(--text-main)] font-semibold">
                            {c.requisitions_live}
                          </span>
                          <span className="text-[var(--text-muted)]">
                            {' '}live / {c.requisitions_raised}
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums
                          text-[var(--text-main)]">{c.candidates}</td>
                        <td className="px-3 py-2.5 text-right tabular-nums
                          text-[var(--text-main)]">{c.joined}</td>
                        <td className={`px-3 py-2.5 text-right tabular-nums font-semibold
                          ${c.waiting_on_client
                            ? 'text-[var(--accent-orange)]'
                            : 'text-[var(--text-muted)]'}`}>
                          {c.waiting_on_client}
                        </td>
                        <td className={`px-3 py-2.5 text-right tabular-nums font-semibold
                          ${c.waiting_on_sparsh
                            ? 'text-[var(--accent-indigo)]'
                            : 'text-[var(--text-muted)]'}`}>
                          {c.waiting_on_sparsh}
                        </td>
                        <td className="px-3 py-2.5 text-right tabular-nums
                          text-[var(--text-main)]">
                          {c.offer_acceptance_rate == null
                            ? '—' : `${c.offer_acceptance_rate}%`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-2 text-[11px] text-[var(--text-muted)]">
                Busiest engagement first. &ldquo;With them&rdquo; is what the client owes
                you, &ldquo;with us&rdquo; is what you owe them.
              </p>
            </div>
          )}

          {isInternal && allClients && !(data.by_client || []).length && (
            <p className="text-[12px] text-[var(--text-muted)]">
              No client engagement has any activity yet. A client company appears here once
              HRMS is switched on for them and they raise their first requirement.
            </p>
          )}

          <p className="text-[11.5px] text-[var(--text-muted)]">
            Acceptance rate counts only offers the candidate answered, so issuing one does
            not drag the figure down while it is still open.
            {isInternal && !allClients
              ? ` Showing ${(clients.find((c) => c.id === picked) || {}).name
                  || companyName || 'the selected client'}.`
              : ''}
          </p>
        </>
      )}
    </div>
  );
};

export default ClientRecruitmentAnalytics;
