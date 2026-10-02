import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  UserCog, Plus, RefreshCw, AlertTriangle, CheckCircle2, X, ShieldAlert, Send,
  Users, Trash2, MessageCircle, Lock, UserPlus,
} from 'lucide-react';
import {
  DashboardHero, HeaderSelect, HeroButton, Section, Th, Td, TableShell, KpiTile, FilterSelect,
} from '../../common/dashboardKit';
import {
  getLeadershipConfig, getLeadershipCycles, getLeadershipSubjects, getLeadershipPeople,
  addLeadershipSubject, removeLeadershipSubject, getLeadershipPanel, saveLeadershipPanel,
  dispatchLeadershipLinks, resendLeadershipLink,
} from '../../../../services/leadershipApi';
import {
  canManage, canManagePanel, errText, useAsync, useLeadershipCompany,
} from '../../leadership/leadershipUtils';
import {
} from '../../leadership/leadershipStatus';

/* ─────────────────────────────────────────────────────────────
   Leadership Score ▸ Leaders & Feedback Givers.

   "HR should identify feedback givers and it should be only known to HR."

   This is the confidentiality boundary in the UI: it is the ONE screen that shows who is
   on a leader's panel, and the backend restricts the endpoints behind it to HR/staff. The
   leader's own result view never receives this data at all — not hidden, not sent.

   The document's recommended panel is 8 people: 2 superiors, 2 peers, 2 from another
   department and 2 direct reports.
   ───────────────────────────────────────────────────────────── */

const MotionDiv = motion.div;

const TONE = {
  green:  { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)' },
  blue:   { c: 'var(--accent-indigo)', bg: 'var(--accent-indigo-bg)', bd: 'var(--accent-indigo-border)' },
  yellow: { c: 'var(--accent-orange)', bg: 'var(--accent-yellow-bg)', bd: 'var(--accent-yellow-border)' },
  red:    { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)' },
  plain:  { c: 'var(--text-muted)',    bg: 'var(--input-bg)',         bd: 'var(--border)' },
};

const Pill = ({ label, tone = 'plain' }) => {
  const s = TONE[tone] || TONE.plain;
  return (
    <span className="inline-flex items-center text-[10px] font-bold tracking-wide uppercase px-2.5 py-1 rounded-full border whitespace-nowrap"
      style={{ color: s.c, background: s.bg, borderColor: s.bd }}>
      {label}
    </span>
  );
};

/** What the status column says for one saved invitation.

    Ordered by what HR needs to see first. A reply ends the story, so Submitted outranks
    everything. A refusal comes next because it is the only state anyone can DO something
    about — an empty mobile field on a person's record. Then sent, then never sent.

    `sent_at` is the test for "gone out" rather than the row status, because it is written
    only on a real delivery — the same field the resend cooldown keys on. A row left over
    from the email era carries it too, which is correct: those were genuinely sent. */
const sendState = (row) => {
  if (row.status === 'submitted') return { label: 'Submitted', tone: 'green' };
  // Ranked above delivery: once the window has closed the link 410s on click, so what
  // matters is that this one is over, not whether it was ever sent. Reading "Awaiting"
  // invited HR to keep pressing Send link against a row the backend will only 409.
  if (row.status === 'expired') return { label: 'Expired', tone: 'yellow' };
  if (row.wa_status === 'unreachable') return { label: 'No number', tone: 'red' };
  if (row.wa_status === 'failed') return { label: 'Not sent', tone: 'red' };
  if (row.sent_at || row.status === 'sent' || row.status === 'opened') {
    return { label: 'Sent', tone: 'blue' };
  }
  return { label: 'Awaiting', tone: 'plain' };
};

const labelCls = 'text-[11px] font-bold uppercase tracking-wide text-[var(--text-muted)]';

const Field = ({ label, hint, children }) => (
  <label className="flex flex-col gap-1.5">
    <span className={labelCls}>{label}</span>
    {children}
    {hint && <span className="text-[10.5px] text-[var(--text-muted)] font-medium">{hint}</span>}
  </label>
);

/** Enrol one leader at a level. */
const SubjectModal = ({ config, people, enrolled, onClose, onSubmit }) => {
  const taken = new Set((enrolled || []).map((s) => String(s.subject_id)));
  const available = (people || []).filter((p) => !taken.has(String(p.person_id)));

  const [personId, setPersonId] = useState(available[0]?.person_id || '');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  // The level is a property of the PERSON, not a choice made at enrolment: the server
  // enrols only at the level on the user's record and rejects anything else. Defaulting
  // the field to L4 therefore guaranteed a mismatch error for every leader who is not L4.
  const picked = available.find((p) => String(p.person_id) === String(personId));
  const level = picked?.leadership_level || '';
  const levelLabel = (config?.levels || []).find((l) => l.code === level)?.label || level;

  const submit = async (e) => {
    e.preventDefault();
    if (!personId) { setErr('Choose a leader.'); return; }
    if (!level) {
      setErr(`${picked?.name || 'This person'} has no Leadership level on their user record. `
        + 'Set it to L4, L5, L6 or L7 on their profile first — it is never guessed from a designation.');
      return;
    }
    setSaving(true);
    setErr('');
    try {
      await onSubmit({ subject_id: personId, level });
    } catch (ex) {
      setErr(errText(ex, 'Could not enrol this leader.'));
      setSaving(false);
    }
  };

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <MotionDiv
        initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }} transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]">
              <UserPlus size={16} />
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">Enrol a Leader</h3>
          </div>
          <button type="button" onClick={onClose} disabled={saving}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>
        <form onSubmit={submit} className="px-5 py-4 space-y-4">
          <Field label="Leader" hint="Applicable from L4 (Asst. Manager) and above.">
            <FilterSelect value={personId} onChange={setPersonId}
              options={available.length
                ? available.map((p) => ({
                    id: p.person_id,
                    // The level rides along in the option, so someone with none is
                    // visible before they are picked rather than after a failed enrol.
                    name: `${p.designation ? `${p.name} — ${p.designation}` : p.name}`
                      + (p.leadership_level ? ` · ${p.leadership_level}` : ' · no level set'),
                  }))
                : [{ id: '', name: 'Everyone is already enrolled' }]} />
          </Field>
          <Field label="Leadership level"
            hint={level
              ? 'Taken from their user record. Decides which set of questions the givers answer.'
              : 'Set this on their user profile before enrolling them.'}>
            <div className={`w-full px-3 py-2 rounded-lg border text-[13px] font-bold ${level
              ? 'bg-[var(--input-bg)] border-[var(--input-border)] text-[var(--text-main)]'
              : 'bg-[var(--accent-red-bg)] border-[var(--accent-red-border)] text-[var(--accent-red)]'}`}>
              {level ? levelLabel : 'No Leadership level on record'}
            </div>
          </Field>
          {err && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} /> {err}
            </div>
          )}
          <div className="flex items-center justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} disabled={saving}
              className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
              Cancel
            </button>
            <button type="submit" disabled={saving || !personId || !level}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
              {saving ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
              {saving ? 'Enrolling…' : 'Enrol Leader'}
            </button>
          </div>
        </form>
      </MotionDiv>
    </MotionDiv>
  );
};

/** Build and dispatch one leader's feedback panel. HR-only content. */
const PanelModal = ({ companyId, cycle, subject, config, people, onClose, onChanged }) => {
  const relations = useMemo(() => {
    const allowed = (config?.degrees || []).find((d) => d.code === (subject.degree || '360'));
    const codes = allowed?.relations || (config?.relations || []).map((r) => r.code);
    return (config?.relations || []).filter((r) => codes.includes(r.code));
  }, [config, subject.degree]);

  const [rows, setRows] = useState([]);          // saved panel (with link status)
  const [draft, setDraft] = useState([]);        // {giver_id, relation}
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState('');
  const [err, setErr] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getLeadershipPanel(companyId, cycle, subject.subject_id);
      const panel = res.data?.panel || [];
      setRows(panel);
      setDraft(panel.map((p) => ({ giver_id: p.giver_id, relation: p.relation })));
      setErr('');
    } catch (e) {
      setErr(errText(e, 'Could not load the panel.'));
    } finally {
      setLoading(false);
    }
  }, [companyId, cycle, subject.subject_id]);

  useEffect(() => { load(); }, [load]);

  const chosen = new Set(draft.map((d) => String(d.giver_id)));
  const candidates = (people || []).filter(
    (p) => String(p.person_id) !== String(subject.subject_id) && !chosen.has(String(p.person_id)));

  const nameOf = (id) => (people || []).find((p) => String(p.person_id) === String(id))?.name
    || rows.find((r) => String(r.giver_id) === String(id))?.giver_name || id;

  // Prefers the invitation's freshly-resolved number, falling back to the roster so a giver
  // who has not been saved yet still shows one.
  const mobileOf = (id, saved) => saved?.giver_mobile
    || (people || []).find((p) => String(p.person_id) === String(id))?.mobile || '';

  const statusOf = (id) => rows.find((r) => String(r.giver_id) === String(id));

  const addGiver = (id, relation) => {
    if (!id) return;
    setDraft((d) => [...d, { giver_id: id, relation }]);
    setNotice('');
  };
  const dropGiver = (id) => {
    const saved = statusOf(id);
    if (saved?.status === 'submitted') {
      setErr('This person has already submitted their feedback and cannot be removed.');
      return;
    }
    setDraft((d) => d.filter((x) => String(x.giver_id) !== String(id)));
    setNotice('');
  };
  const setRelation = (id, relation) => {
    setDraft((d) => d.map((x) => (String(x.giver_id) === String(id) ? { ...x, relation } : x)));
  };

  const save = async () => {
    setSaving(true);
    setErr('');
    setNotice('');
    try {
      await saveLeadershipPanel(companyId, cycle, subject.subject_id, draft);
      setNotice('Panel saved. Each new member now has a personal feedback link.');
      await load();
      onChanged?.();
    } catch (e) {
      setErr(errText(e, 'Could not save the panel.'));
    } finally {
      setSaving(false);
    }
  };

  const dispatch = async () => {
    setSaving(true);
    setErr('');
    setNotice('');
    try {
      const res = await dispatchLeadershipLinks(companyId, cycle, subject.subject_id);
      const {
        sent = 0, failed = 0, unreachable = 0,
        skipped_recent: held = 0, cooldown_hours: cd = 24,
      } = res.data || {};
      // Every reason a link did NOT go is named. Reporting only `sent` turned a batch that
      // was entirely held back by the cooldown into a bare "0 links sent on WhatsApp",
      // which reads as a broken button rather than as working exactly as intended.
      const parts = [`${sent} link${sent === 1 ? '' : 's'} sent on WhatsApp`];
      if (failed) parts.push(`${failed} refused`);
      if (unreachable) parts.push(`${unreachable} with no mobile number`);
      if (held) parts.push(`${held} already sent in the last ${cd}h and skipped`);
      setNotice(`${parts.join(', ')}.`);
      await load();
      onChanged?.();
    } catch (e) {
      setErr(errText(e, 'Could not send the links.'));
    } finally {
      setSaving(false);
    }
  };

  const resend = async (id) => {
    setBusyId(id);
    setErr('');
    try {
      await resendLeadershipLink(id);
      // The route 4xx's on a refusal, so reaching here means it really went. Worded to
      // agree with the row, which now reads Sent — "Link re-sent" above a row still
      // saying Awaiting was the whole confusion.
      setNotice('Link sent on WhatsApp.');
      await load();
    } catch (e) {
      setErr(errText(e, 'Could not re-send the link.'));
    } finally {
      setBusyId('');
    }
  };

  const perRelation = (code) => draft.filter((d) => d.relation === code).length;
  const dirty = JSON.stringify([...draft].sort((a, b) => String(a.giver_id).localeCompare(String(b.giver_id))))
    !== JSON.stringify(rows.map((p) => ({ giver_id: p.giver_id, relation: p.relation }))
      .sort((a, b) => String(a.giver_id).localeCompare(String(b.giver_id))));

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <MotionDiv
        initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }} transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-3xl max-h-[88vh] overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl">
        <div className="sticky top-0 z-10 flex items-center justify-between px-5 py-4 border-b border-[var(--border)] bg-[var(--bg-card)]">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] shrink-0">
              <Users size={16} />
            </span>
            <div className="min-w-0">
              <h3 className="text-[15px] font-extrabold tracking-tight truncate">
                Feedback Panel — {subject.subject_name}
              </h3>
              <p className="text-[11px] text-[var(--text-muted)]">
                {subject.level_label} · known only to HR
              </p>
            </div>
          </div>
          <button type="button" onClick={onClose} disabled={saving}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50 shrink-0">
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          <div className="flex items-start gap-2 rounded-xl bg-[var(--accent-green-bg)] px-4 py-3">
            <Lock size={14} className="text-[var(--accent-green)] mt-0.5 shrink-0" />
            <p className="text-[12px] font-medium text-[var(--accent-green)]">
              This list is visible to HR and administrators only. {subject.subject_name} sees a
              combined score and never learns who was on their panel or who gave which rating.
            </p>
          </div>

          {/* Panel composition against the document's recommended 2-per-relation. */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {relations.map((r) => {
              const n = perRelation(r.code);
              return (
                <div key={r.code} className="rounded-xl border border-[var(--border)] px-3 py-2.5">
                  <p className="text-[10.5px] font-bold uppercase tracking-wide text-[var(--text-muted)] leading-tight">
                    {r.label}
                  </p>
                  <p className="text-[16px] font-extrabold tabular-nums mt-1"
                    style={{ color: n >= 2 ? 'var(--accent-green)' : 'var(--text-muted)' }}>
                    {n}<span className="text-[11px] font-bold text-[var(--text-muted)]"> / 2</span>
                  </p>
                </div>
              );
            })}
          </div>

          {loading ? (
            <div className="py-10 text-center text-[13px] font-bold text-[var(--text-muted)]">Loading panel…</div>
          ) : (
            <>
              <TableShell minWidth={620}>
                <thead>
                  <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                    <Th>Feedback giver</Th><Th>Relation</Th>
                    <Th align="center">Link</Th><Th align="right">Actions</Th>
                  </tr>
                </thead>
                <tbody>
                  {draft.length === 0 ? (
                    <tr><Td colSpan={4}>
                      <span className="block py-6 text-center text-[12.5px] text-[var(--text-muted)]">
                        No feedback givers yet. Add up to 8 below.
                      </span>
                    </Td></tr>
                  ) : draft.map((g) => {
                    const saved = statusOf(g.giver_id);
                    return (
                      <tr key={g.giver_id} className="border-b border-[var(--border)] last:border-0">
                        <Td>
                          <span className="font-bold">{nameOf(g.giver_id)}</span>
                          {/* The NUMBER, not the email — links go by WhatsApp, so this is
                              the address that decides whether they can be reached. Shown
                              missing rather than omitted: a blank line reads as "no data",
                              and this person simply will not receive their invitation. */}
                          {mobileOf(g.giver_id, saved) ? (
                            <span className="block text-[10.5px] font-mono text-[var(--text-muted)]">
                              {mobileOf(g.giver_id, saved)}
                            </span>
                          ) : (
                            <span className="block text-[10.5px] font-bold text-[var(--accent-red)]">
                              No mobile number — cannot be invited
                            </span>
                          )}
                          {/* Why the last attempt was refused. Meta's wording, unedited —
                              a paraphrase would send HR looking for the wrong thing. */}
                          {saved?.wa_error && (
                            <span className="block text-[10.5px] font-semibold text-[var(--accent-red)]">
                              {saved.wa_error}
                            </span>
                          )}
                        </Td>
                        <Td>
                          <FilterSelect value={g.relation}
                            onChange={(v) => setRelation(g.giver_id, v)}
                            options={relations.map((r) => ({ id: r.code, name: r.label }))} />
                        </Td>
                        <Td align="center">
                          {/* Two different questions share this column, and pressing Send
                              link only answers the second: has this person REPLIED, and has
                              their invitation gone out. Showing only the first made a
                              successful send look identical to one that never happened.
                              Still not Meta's delivery state — no delivered/read receipts,
                              nothing that changes after the fact. Just whether we sent it,
                              and whether sending was refused, which is the part HR can act
                              on. */}
                          {saved ? <Pill {...sendState(saved)} /> : <Pill label="Not saved" tone="yellow" />}
                        </Td>
                        <Td align="right">
                          <div className="inline-flex items-center gap-1.5 justify-end">
                            {saved && saved.status !== 'submitted' && (
                              <button type="button" onClick={() => resend(saved.id)} disabled={busyId === saved.id}
                                className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity disabled:opacity-50">
                                {busyId === saved.id ? <RefreshCw size={12} className="animate-spin" /> : <MessageCircle size={12} />}
                                Send link
                              </button>
                            )}
                            {saved?.status !== 'submitted' && (
                              <button type="button" onClick={() => dropGiver(g.giver_id)}
                                className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-red)] bg-[var(--accent-red-bg)] border border-[var(--accent-red-border)] hover:opacity-90 transition-opacity">
                                <Trash2 size={12} />
                              </button>
                            )}
                          </div>
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </TableShell>

              {/* Add a giver */}
              <div className="rounded-xl border border-[var(--border)] p-3.5 grid gap-2 sm:grid-cols-[1fr_auto_auto] items-end">
                <Field label="Add feedback giver">
                  <FilterSelect value="" onChange={(v) => addGiver(v, relations[0]?.code)}
                    options={[{ id: '', name: 'Select a person…' },
                              ...candidates.map((p) => ({
                                id: p.person_id,
                                name: p.designation ? `${p.name} — ${p.designation}` : p.name,
                              }))]} />
                </Field>
                <span className="text-[10.5px] text-[var(--text-muted)] pb-2.5">
                  Recommended panel: 8 people
                </span>
              </div>
            </>
          )}

          {err && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} /> {err}
            </div>
          )}
          {notice && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-green)]">
              <CheckCircle2 size={14} /> {notice}
            </div>
          )}
        </div>

        <div className="sticky bottom-0 flex flex-wrap items-center justify-end gap-2 px-5 py-4 border-t border-[var(--border)] bg-[var(--bg-card)]">
          <button type="button" onClick={onClose} disabled={saving}
            className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            Close
          </button>
          {/* Same rule as the cycle-wide button: a closed or elapsed cycle sends nothing. */}
          <button type="button" onClick={dispatch}
            disabled={saving || dirty || rows.length === 0 || subject?.can_dispatch === false}
            title={subject?.can_dispatch === false
              ? 'This cycle is closed or its window has ended — links can no longer be sent.'
              : undefined}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--accent-green)] bg-[var(--accent-green-bg)] border border-[var(--accent-green-border)] hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed">
            <Send size={14} /> Send pending links
          </button>
          <button type="button" onClick={save} disabled={saving || !dirty}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed">
            {saving ? <RefreshCw size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
            {saving ? 'Saving…' : 'Save Panel'}
          </button>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

/** The two actions on this page that could not be taken back quietly, and until now fired
    straight off a click: un-enrolling a leader (which destroys the panel built for them and
    kills links already delivered) and sending every pending invitation at once.

    One component for both, driven by props, so a third such action has somewhere to go
    rather than reaching for a browser confirm. */
const ConfirmModal = ({ icon, tone, title, subtitle, children,
                       confirmLabel, busyLabel, onClose, onConfirm }) => {
  // Bound as a local rather than renamed in the destructure: no-unused-vars exempts
  // capitalised VARS here but holds destructured ARGS to the `^_` pattern, and it does not
  // count a JSX element name as a use. Same reason this file aliases MotionDiv.
  const Icon = icon;
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !saving) onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [saving, onClose]);

  const go = async () => {
    setSaving(true);
    setErr('');
    try {
      await onConfirm();
    } catch (e) {
      // Reported in here rather than behind the overlay, so the dialog stays put and the
      // action can be retried without finding the row again.
      setErr(errText(e, 'That did not work.'));
      setSaving(false);
    }
  };

  return (
    <MotionDiv className="fixed inset-0 z-50 flex items-center justify-center p-4"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={saving ? undefined : onClose} />
      <MotionDiv role="alertdialog" aria-modal="true"
        initial={{ opacity: 0, y: 14, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 14, scale: 0.98 }}
        transition={{ duration: 0.22, ease: [0.4, 0, 0.2, 1] }}
        className="relative w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] shadow-xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
              style={{ color: `var(--accent-${tone})`, background: `var(--accent-${tone}-bg)` }}>
              <Icon size={16} />
            </span>
            <div className="min-w-0">
              <h3 className="text-[15px] font-extrabold tracking-tight">{title}</h3>
              {subtitle && (
                <span className="block text-[10.5px] font-bold text-[var(--text-muted)] truncate">{subtitle}</span>
              )}
            </div>
          </div>
          <button type="button" onClick={onClose} disabled={saving}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3">
          {children}
          {err && (
            <div className="flex items-center gap-2 rounded-lg border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3 py-2 text-[12px] font-bold text-[var(--accent-red)]">
              <AlertTriangle size={14} /> {err}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-[var(--border)]">
          <button type="button" onClick={onClose} disabled={saving}
            className="px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
            Cancel
          </button>
          <button type="button" onClick={go} disabled={saving} autoFocus
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40"
            style={{ background: `var(--accent-${tone})` }}>
            {saving ? <RefreshCw size={14} className="animate-spin" /> : <Icon size={14} />}
            {saving ? busyLabel : confirmLabel}
          </button>
        </div>
      </MotionDiv>
    </MotionDiv>
  );
};

const LeadershipSubjects = () => {
  const { user, staff, companyOptions, companyId, setCompanyId } = useLeadershipCompany();
  const manage = canManage(user);
  // Narrower than `manage`: only HR (and internal staff) may see or change a panel.
  const managePanel = canManagePanel(user);
  const [params, setParams] = useSearchParams();
  const [cycle, setCycle] = useState(params.get('cycle') || '');
  const [adding, setAdding] = useState(false);
  const [panelFor, setPanelFor] = useState(null);
  const [pendingUnenrol, setPendingUnenrol] = useState(null);
  const [confirmDispatch, setConfirmDispatch] = useState(false);
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');

  const waiting = staff && !companyId;

  const cfg = useAsync(async () => (await getLeadershipConfig()).data, [], { skip: !manage });
  const cyc = useAsync(
    async () => (await getLeadershipCycles(companyId)).data,
    [companyId], { skip: waiting || !manage },
  );
  const people = useAsync(
    async () => (await getLeadershipPeople(companyId)).data,
    [companyId], { skip: waiting || !manage },
  );

  const cycles = useMemo(() => cyc.data?.cycles || [], [cyc.data]);

  // Land on the newest cycle once they load, unless the URL named one.
  useEffect(() => {
    if (!cycle && cycles.length) setCycle(cycles[0].cycle);
  }, [cycles, cycle]);

  const load = useMemo(
    () => async () => (await getLeadershipSubjects(companyId, cycle)).data,
    [companyId, cycle],
  );
  const { data, loading, error, setError, reload } = useAsync(load, [companyId, cycle],
    { skip: waiting || !cycle || !manage });

  const subjects = data?.subjects || [];
  const activeCycle = cycles.find((c) => c.cycle === cycle);
  // Server-computed (leadership_service.list_cycles) so the UI and assert_dispatchable
  // can never disagree about whether a cycle still accepts invitations.
  const canDispatch = activeCycle?.can_dispatch !== false;

  const pickCycle = (v) => {
    setCycle(v);
    setParams(v ? { cycle: v } : {});
  };

  const enrol = async (payload) => {
    await addLeadershipSubject(companyId, cycle, payload);
    setAdding(false);
    setNotice('Leader enrolled. Assign their feedback panel next.');
    await reload();
  };

  // Left to throw: ConfirmModal reports the failure in place. The row is only dropped
  // from the dialog once the server has actually removed it.
  const unenrol = async (subjectId) => {
    setBusy(subjectId);
    setError('');
    setNotice('');
    try {
      await removeLeadershipSubject(companyId, cycle, subjectId);
      setPendingUnenrol(null);
      setNotice('Leader removed from this cycle.');
      await reload();
    } finally {
      setBusy('');
    }
  };

  const dispatchAll = async () => {
    setConfirmDispatch(false);
    setBusy('all');
    setError('');
    setNotice('');
    try {
      const res = await dispatchLeadershipLinks(companyId, cycle);
      const {
        sent = 0, failed = 0, unreachable = 0,
        skipped_recent: held = 0, cooldown_hours: cd = 24,
        skipped_incomplete: incomplete = [],
      } = res.data || {};
      const parts = [`${sent} link${sent === 1 ? '' : 's'} sent on WhatsApp`];
      if (failed) parts.push(`${failed} refused`);
      // Counted apart from a refusal: an empty mobile field is fixed on the person's
      // record, a refusal is fixed with Meta. Merging them sends HR to the wrong screen.
      if (unreachable) parts.push(`${unreachable} with no mobile number`);
      // Say what was held and why, so a second click reads as deliberate rather than broken.
      if (held) parts.push(`${held} already sent in the last ${cd}h and skipped`);
      // Leaders whose panel is still short are named rather than counted: "2 skipped" leaves
      // HR hunting for which two, and the whole point is that they can go and finish them.
      if (incomplete.length) {
        parts.push(`${incomplete.length} panel${incomplete.length === 1 ? '' : 's'} not yet complete `
          + `(${incomplete.map((x) => `${x.subject_name} needs ${x.needs}`).join('; ')})`);
      }
      setNotice(`${parts.join(', ')}.`);
      await reload();
    } catch (e) {
      setError(errText(e, 'Could not send the links.'));
    } finally {
      setBusy('');
    }
  };

  if (!manage) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 px-5 py-20 text-center">
        <span className="w-12 h-12 rounded-2xl bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center">
          <ShieldAlert size={22} />
        </span>
        <p className="text-[14px] font-bold">HR and administrators only</p>
        <p className="text-[12.5px] text-[var(--text-muted)] max-w-sm">
          Feedback givers are identified by HR and are known only to HR.
        </p>
      </div>
    );
  }

  const totalPanel = subjects.reduce((s, x) => s + (x.panel_size || 0), 0);
  const totalDone = subjects.reduce((s, x) => s + (x.submitted_count || 0), 0);

  return (
    <div className="space-y-5">
      <DashboardHero icon={UserCog} title="Leadership Score — Leaders"
        subtitle={managePanel
          ? 'Enrol leaders and assign each a confidential feedback panel'
          : 'Enrol leaders — feedback panels are managed by HR'}>
        {staff && <HeaderSelect value={companyId} onChange={setCompanyId} options={companyOptions} />}
        <HeaderSelect value={cycle} onChange={pickCycle}
          options={cycles.length ? cycles.map((c) => ({ id: c.cycle, name: c.label }))
            : [{ id: '', name: 'No cycles yet' }]} />
        <HeroButton icon={Plus} onClick={() => setAdding(true)}>Enrol Leader</HeroButton>
        {/* Dispatch acts on the panel, so it follows the same HR-only gate. Hidden entirely
            for a closed or elapsed cycle — the API refuses it either way (409), so showing
            a button that cannot work would only invite the error. */}
        {managePanel && canDispatch && (
          <HeroButton icon={Send} onClick={() => setConfirmDispatch(true)}>
            {busy === 'all' ? 'Sending…' : 'Send All Pending'}
          </HeroButton>
        )}
      </DashboardHero>

      {managePanel && cycle && !canDispatch && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--border)] bg-[var(--input-bg)] px-4 py-3 text-[12px] font-bold text-[var(--text-muted)]">
          <Send size={15} />
          {activeCycle?.status === 'closed'
            ? `${activeCycle?.label || cycle} is closed — its scores are final, so no further invitations or reminders can be sent.`
            : `The ${activeCycle?.label || cycle} window has ended — feedback links have expired, so nothing further can be sent.`}
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-red)]">
          <AlertTriangle size={15} /> {error}
        </div>
      )}
      {notice && (
        <div className="flex items-center gap-2 rounded-2xl border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] px-4 py-3 text-[12px] font-bold text-[var(--accent-green)]">
          <CheckCircle2 size={15} /> {notice}
        </div>
      )}

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        <KpiTile value={subjects.length} label="Leaders" sub="Enrolled this cycle" tone="blue" icon={UserCog} />
        <KpiTile value={totalPanel} label="Feedback givers" sub="Links issued" tone="blue" icon={Users} />
        <KpiTile value={totalDone} label="Submitted" sub="Responses received" tone={totalDone ? 'green' : 'plain'} icon={CheckCircle2} />
        <KpiTile value={totalPanel - totalDone} label="Pending" sub="Awaiting feedback"
          tone={totalPanel - totalDone ? 'yellow' : 'plain'} icon={MessageCircle} />
      </div>

      <Section title="Enrolled Leaders" icon={UserCog}
        subtitle={cycle ? `${activeCycle?.label || cycle} · ${activeCycle?.degree || '360'}° feedback` : 'Select a cycle'}>
        {waiting ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Select a company.
          </div>
        ) : !cycle ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Open an assessment cycle first.
          </div>
        ) : loading ? (
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Loading leaders…
          </div>
        ) : subjects.length === 0 ? (
          <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
            <span className="w-11 h-11 rounded-2xl bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)] flex items-center justify-center">
              <UserCog size={20} />
            </span>
            <p className="text-[13px] font-bold">No leaders enrolled yet</p>
            <p className="text-[12px] text-[var(--text-muted)] max-w-sm">
              Leadership Score applies from L4 (Asst. Manager) and above.
            </p>
          </div>
        ) : (
          <TableShell minWidth={900}>
            <thead>
              <tr className="bg-[var(--table-header-bg)] border-b border-[var(--border)]">
                <Th>Leader</Th><Th>Level</Th><Th align="center">Panel</Th>
                <Th align="center">Submitted</Th><Th align="right">Actions</Th>
              </tr>
            </thead>
            <tbody>
              {subjects.map((s) => (
                <tr key={s.subject_id} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--table-hover)] transition-colors">
                  <Td>
                    <span className="font-bold">{s.subject_name}</span>
                    {(s.designation || s.department) && (
                      <span className="block text-[10.5px] text-[var(--text-muted)]">
                        {[s.designation, s.department].filter(Boolean).join(' · ')}
                      </span>
                    )}
                  </Td>
                  <Td><Pill label={s.level} tone="blue" /></Td>
                  {/* Against THIS leader's own degree. A complete 180° panel is four
                      people, and printing "/ 8" made it read as half-built. */}
                  <Td align="center" className="tabular-nums font-bold">
                    {s.panel_size ?? 0}
                    <span className="text-[10px] text-[var(--text-muted)]"> / {s.panel_target ?? 8}</span>
                  </Td>
                  <Td align="center" className="tabular-nums font-bold"
                    style={{ color: s.submitted_count ? 'var(--accent-green)' : 'var(--text-muted)' }}>
                    {s.submitted_count ?? 0}
                  </Td>
                  <Td align="right">
                    <div className="inline-flex items-center gap-1.5 justify-end">
                      {/* Panel = giver identity. HR (and internal staff) only — a
                          clientadmin enrols leaders but never sees who rates them. */}
                      {managePanel && (
                        <button type="button" onClick={() => setPanelFor({ ...s, degree: activeCycle?.degree, can_dispatch: canDispatch })}
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border border-[var(--accent-indigo-border)] hover:opacity-90 transition-opacity">
                          <Users size={12} /> Panel
                        </button>
                      )}
                      {!s.submitted_count && (
                        <button type="button" onClick={() => setPendingUnenrol(s)} disabled={busy === s.subject_id}
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[11.5px] font-bold text-[var(--accent-red)] bg-[var(--accent-red-bg)] border border-[var(--accent-red-border)] hover:opacity-90 transition-opacity disabled:opacity-50">
                          <Trash2 size={12} />
                        </button>
                      )}
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableShell>
        )}
      </Section>

      <AnimatePresence>
        {adding && (
          <SubjectModal key="add-subject" config={cfg.data} people={people.data?.people}
            enrolled={subjects} onClose={() => setAdding(false)} onSubmit={enrol} />
        )}
        {panelFor && managePanel && (
          <PanelModal key={`panel-${panelFor.subject_id}`} companyId={companyId} cycle={cycle}
            subject={panelFor} config={cfg.data} people={people.data?.people}
            onClose={() => setPanelFor(null)} onChanged={reload} />
        )}
        {pendingUnenrol && (
          <ConfirmModal key="unenrol" icon={Trash2} tone="red"
            title="Remove this leader from the cycle?"
            subtitle={pendingUnenrol.subject_name}
            confirmLabel="Remove Leader" busyLabel="Removing…"
            onClose={() => setPendingUnenrol(null)}
            onConfirm={() => unenrol(pendingUnenrol.subject_id)}>
            {pendingUnenrol.panel_size > 0 ? (
              <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-yellow)]">
                <AlertTriangle size={14} className="mt-[1px] shrink-0" />
                <span>
                  The panel of <b>{pendingUnenrol.panel_size}</b> feedback
                  giver{pendingUnenrol.panel_size === 1 ? '' : 's'} built for them is deleted with
                  them, and any invitation already sent stops working.
                </span>
              </div>
            ) : (
              <p className="text-[12.5px] font-medium text-[var(--text-muted)]">
                No panel has been assigned yet, so nothing else goes with them.
              </p>
            )}
            <p className="text-[12.5px] font-medium text-[var(--text-muted)]">
              They can be enrolled again while the cycle is still collecting.
            </p>
          </ConfirmModal>
        )}
        {confirmDispatch && (
          <ConfirmModal key="dispatch-all" icon={Send} tone="indigo"
            title="Send every pending invitation?"
            subtitle={activeCycle?.label || cycle}
            confirmLabel="Send Invitations" busyLabel="Sending…"
            onClose={() => setConfirmDispatch(false)}
            onConfirm={dispatchAll}>
            <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
              Every feedback giver across
              this cycle&rsquo;s <b className="text-[var(--text-main)]">{subjects.length} enrolled
              leader{subjects.length === 1 ? '' : 's'}</b> who has not yet submitted is sent
              their own link on WhatsApp. These reach real phones and cannot be recalled.
            </p>
            <p className="text-[12.5px] font-medium text-[var(--text-muted)]">
              Anyone already messaged recently is held back by the resend cooldown, and leaders
              whose panel is not yet complete are skipped and named in the result — so pressing
              this again to chase is safe.
            </p>
          </ConfirmModal>
        )}
      </AnimatePresence>
    </div>
  );
};

export default LeadershipSubjects;
