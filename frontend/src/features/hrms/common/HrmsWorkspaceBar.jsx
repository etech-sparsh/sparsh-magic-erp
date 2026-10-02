import React from 'react';
import { Link, useLocation, useSearchParams } from 'react-router-dom';
import { useHrms } from '../HrmsContext';
import { WORKSPACES } from './hrmsWorkspaces';

/**
 * HRMS ▸ workspace bar.
 *
 * The module's own chrome: identity + breadcrumb on the left, a tab strip underneath.
 * Purely navigational — every tab points at a route that already exists (see App.jsx), so
 * this is a different way to reach those screens, never a new one.
 *
 * -- One bar, several workspaces -----------------------------------------------------
 * The strips themselves live in `hrmsWorkspaces.js` as data: hiring (raise → post →
 * screen → assess → interview → offer → report) and onboarding (pre-joiner → case →
 * appointment → induction → surveys → probation). This component renders WHICHEVER
 * workspace owns the current route, which is what keeps the two strips looking and
 * behaving identically — a person who has learnt one has learnt the other. The sidebar
 * keeps Dashboard, Employees, the masters, and the standalone boards (Exit, Exceptions).
 *
 * Every tab is shown only when the caller actually holds the capability its screen requires
 * (mirroring each route's own `_require(...)` in backend/app/routes/hrms.py exactly). A tab
 * with `cap: null` has no capability gate on its route (Interviews: "seeing the interview
 * you were booked for is an inherent right", per that route's own docstring) and always
 * shows. This is a UX kindness layered on a check the API already enforces, not a new
 * security boundary — a screen that somehow renders anyway still gets nothing back from the
 * API. A phase left with no visible tabs is dropped entirely rather than shown as an empty
 * label, so a caller who holds nothing in, say, "After Joining" never sees that heading.
 */

// Prefix match, so a detail route under a stage keeps that stage's tab lit. Anything added
// here whose path is a PREFIX of the others — '/hrms' itself, notably — needs an exact
// match instead, or it silently claims every screen in the module.
//
// A tab carrying `stage` is a panel on a single-page workspace (Client Hiring) rather than
// a route of its own: it matches on `?stage=` at that workspace's home, and the first such
// tab the caller can see also owns the bare URL, because that is the panel the board itself
// falls back to. Prefix matching alone would give every client tab to whichever came first.
const owns = (tab, pathname, stage, isDefaultStage) => {
  if (tab.stage) {
    return pathname === tab.to.split('?')[0]
      && (stage === tab.stage || (!stage && isDefaultStage));
  }
  return pathname === tab.to || pathname.startsWith(`${tab.to}/`);
};

const HrmsWorkspaceBar = () => {
  const { pathname } = useLocation();
  const [params] = useSearchParams();
  const { can } = useHrms();

  // Each tab shows only when the caller holds its own screen's capability. A phase left
  // with no visible tabs is dropped entirely rather than shown as an empty heading.
  const allowed = React.useMemo(() => WORKSPACES.map((ws) => ({
    ...ws,
    phases: ws.phases
      .map((phase) => ({ ...phase, tabs: phase.tabs.filter((t) => !t.cap || can(t.cap)) }))
      .filter((phase) => phase.tabs.length > 0),
  })), [can]);

  // The first workspace that owns this route wins. No path appears in two workspaces —
  // `test_client_ui_contract` asserts that, so "first" is also "only".
  const stage = params.get('stage');
  const hit = (() => {
    for (const ws of allowed) {
      // Whichever stage tab this caller sees first is the workspace's default panel.
      const firstStage = ws.phases.flatMap((p) => p.tabs).find((t) => t.stage)?.stage;
      for (const phase of ws.phases) {
        const tab = phase.tabs.find(
          (t) => owns(t, pathname, stage, t.stage === firstStage));
        if (tab) return { workspace: ws, activePhase: phase, active: tab };
      }
    }
    return null;
  })();

  // Employee and master screens are a different job — they keep their plain page header.
  if (!hit) return null;
  const { workspace, activePhase, active } = hit;

  const WorkspaceIcon = workspace.icon;

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] px-4 sm:px-5 pt-3.5">
      <div className="flex items-center gap-3">
        <div className="h-9 w-9 rounded-xl bg-[var(--accent-indigo)] text-white grid place-items-center shrink-0">
          <WorkspaceIcon size={17} />
        </div>
        <div className="min-w-0">
          {/* The breadcrumb names the WORKSPACE and the PHASE, not just the screen — "which
              job am I doing, and where am I in it" is the question a strip covering a whole
              journey has to answer before anything else. */}
          <div className="flex items-baseline gap-1.5 flex-wrap">
            <span className="text-[17px] font-bold tracking-tight text-[var(--text-main)]">
              {workspace.title}
            </span>
            <span className="text-[14px] text-[var(--text-muted)]">/</span>
            <span className="text-[13px] font-bold tracking-tight text-[var(--accent-indigo)]">
              {activePhase.label}
            </span>
            <span className="text-[14px] text-[var(--text-muted)]">/</span>
            <span className="text-[15px] font-bold tracking-tight text-[var(--text-main)]">
              {active.label}
            </span>
          </div>
          <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
            {activePhase.hint}
          </p>
        </div>
      </div>

      {/* A rule under the identity row so the strip reads as tabs belonging to this
          workspace, rather than a row of buttons floating in a card. */}
      <nav className="mt-3 pt-2.5 pb-2.5 border-t border-[var(--border)] flex items-center gap-1 overflow-x-auto no-scrollbar">
        {workspace.phases.map((phase, gi) => (
          <React.Fragment key={phase.key}>
            {gi > 0 && (
              <span aria-hidden="true"
                className="shrink-0 self-stretch w-px bg-[var(--border)] mx-1.5 my-0.5" />
            )}
            <span className="shrink-0 pl-1 pr-1.5 text-[10px] font-bold uppercase
              tracking-widest text-[var(--text-muted)]">
              {phase.label}
            </span>
            {/* A plain Link, not a NavLink: NavLink decides `isActive` from the path
                alone and cannot see `?stage=`, so on a single-page workspace it would
                light every tab at once. The scan above already found the one active tab
                for both kinds, so it is the single source of truth here too. */}
            {phase.tabs.map((tab) => (
              <Link
                key={tab.to}
                to={tab.to}
                aria-current={tab === active ? 'page' : undefined}
                className={`
                  shrink-0 h-8 px-3.5 rounded-full flex items-center gap-1.5 text-[12px]
                  font-bold tracking-tight transition-colors whitespace-nowrap
                  ${tab === active
                    ? 'bg-[var(--accent-indigo)] text-white shadow-sm'
                    : 'text-[var(--text-muted)] hover:bg-[var(--input-bg)] hover:text-[var(--text-main)]'}
                `}
              >
                <tab.icon size={13} />
                {tab.label}
              </Link>
            ))}
          </React.Fragment>
        ))}
      </nav>
    </div>
  );
};

export default HrmsWorkspaceBar;
