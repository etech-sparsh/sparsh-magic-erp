import React, { useCallback, useMemo, useState } from 'react';
import { AnimatePresence } from 'framer-motion';
import {
  MessageCircle, RefreshCw, AlertTriangle, CheckCircle2, ShieldAlert,
  Send, Clock, XCircle, Info, FileCheck2, Pencil, Plus,
} from 'lucide-react';
import { DashboardHero, HeroButton, Section } from '../../common/dashboardKit';
import LeadershipTemplateModal from './LeadershipTemplateModal';
import {
  getLeadershipWhatsAppLog,
  getLeadershipWhatsAppTemplate, submitLeadershipWhatsAppTemplate,
  syncLeadershipWhatsAppTemplate, checkLeadershipWaTemplate, saveLeadershipWaDraft,
} from '../../../../services/leadershipApi';
import { canManageTemplate, errText, parseUtc, useAsync } from '../../leadership/leadershipUtils';
import { useAuth } from '../../../../context/AuthContext';

/* ─────────────────────────────────────────────────────────────
   Leadership Score ▸ WhatsApp Template.

   Write the invitation here, submit it to Meta, and watch it move to Approved. Nothing can
   be sent until Meta has approved it — Meta renders every business-initiated message from
   its OWN approved copy, so an unapproved name fails per recipient with nothing on screen
   to explain why. Showing the verdict here is what makes that visible before it matters.

   ONE TEMPLATE, EVERY COMPANY. There is no company picker because there is nothing to
   pick: the invitation says the same thing to everybody, and the three things that differ
   per recipient — who is asking, who they are rating, and their link — arrive as variables
   filled when the message is sent. Writing it once means it is approved once, rather than
   every client waiting on their own review of the same sentence.

   The cost is real and worth knowing: editing sends it back to Draft for EVERYONE, so no
   invitations go out anywhere until Meta approves it again.

   ENTIRELY SEPARATE FROM TPMS. Leadership's templates live in their own collection with
   their own endpoints; a TPMS template change cannot alter a feedback invitation.

   Editing the wording sends it back to Draft on purpose. Meta reviews CONTENT, so a
   template whose text changed locally is no longer the thing that was approved.
   ───────────────────────────────────────────────────────────── */

// DRAFT is ours — written here, never sent to Meta. The other three are Meta's verdict,
// mirrored locally so the page can answer "where is it up to?" without a round trip.
const TPL_TONE = {
  DRAFT:    { c: 'var(--text-muted)',    bg: 'var(--input-bg)',         bd: 'var(--border)',               icon: Clock,      label: 'Draft — not submitted' },
  PENDING:  { c: 'var(--accent-yellow)', bg: 'var(--accent-yellow-bg)', bd: 'var(--accent-yellow-border)', icon: Send,       label: 'Pending Meta review' },
  APPROVED: { c: 'var(--accent-green)',  bg: 'var(--accent-green-bg)',  bd: 'var(--accent-green-border)',  icon: FileCheck2, label: 'Approved' },
  REJECTED: { c: 'var(--accent-red)',    bg: 'var(--accent-red-bg)',    bd: 'var(--accent-red-border)',    icon: XCircle,    label: 'Rejected' },
};

const StatusPill = ({ value }) => {
  const s = TPL_TONE[value] || TPL_TONE.DRAFT;
  const Icon = s.icon;
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide px-3 py-1.5 rounded-full border whitespace-nowrap"
      style={{ color: s.c, background: s.bg, borderColor: s.bd }}>
      <Icon size={12} /> {s.label}
    </span>
  );
};

const stamp = (value) => {
  const d = parseUtc(value);
  return d && d.toLocaleString(undefined,
    { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
};

/** `embedded` — rendered inside Notification Templates, which supplies the page header. */
const LeadershipWhatsApp = ({ embedded = false }) => {
  const { user } = useAuth();
  // Administrators only — superadmin, admin, client admin. Writing the invitation is an
  // administrative decision, and HR does not need the screen to send links.
  const manage = canManageTemplate(user);

  const [composerOpen, setComposerOpen] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const loadTemplate = useCallback(
    async () => (await getLeadershipWhatsAppTemplate()).data, []);
  const { data: template, loading, reload } = useAsync(loadTemplate, [], { skip: !manage });

  const status = template?.status || 'DRAFT';

  // The ledger is the one thing here that is still per company — a send belongs to one.
  // Staff name no company and see every attempt; a client user is pinned to their own by
  // the server.
  const loadLog = useCallback(async () => (await getLeadershipWhatsAppLog()).data, []);
  const { data: log, reload: reloadLog } = useAsync(loadLog, [], { skip: !manage });
  // `can_edit` from the server is the authority; the same rule is applied locally so the
  // authoring controls are never rendered and then refused.
  const mayEdit = manage && template?.can_edit !== false;

  // The modal only ever deals in a message; there is one template behind these calls.
  const templateApi = useMemo(() => ({
    check: (doc) => checkLeadershipWaTemplate(doc),
    save: (doc) => saveLeadershipWaDraft(doc),
    submit: () => submitLeadershipWhatsAppTemplate(),
  }), []);

  const run = async (kind, fn, failure) => {
    setBusy(kind);
    setError('');
    setNotice('');
    try {
      const res = await fn();
      setNotice([res?.data?.message, res?.data?.note].filter(Boolean).join(' '));
      await reload();
    } catch (e) {
      setError(errText(e, failure));
    } finally {
      setBusy('');
    }
  };

  const submit = () => run('submit', () => submitLeadershipWhatsAppTemplate(),
    'Could not submit the template to Meta.');

  const refreshStatus = () => run('sync', () => syncLeadershipWhatsAppTemplate(),
    'Could not check the status with Meta.');

  const LOG_TONE = {
    read: 'green', delivered: 'green', sent: 'blue',
    failed: 'red', unreachable: 'red', pending: 'plain',
  };

  if (!manage) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 px-5 py-20 text-center">
        <span className="w-12 h-12 rounded-2xl bg-[var(--accent-red-bg)] text-[var(--accent-red)] flex items-center justify-center">
          <ShieldAlert size={22} />
        </span>
        <p className="text-[14px] font-bold">Administrators only</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {embedded ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3 shadow-sm">
          <div className="min-w-0">
            <p className="text-[13px] font-extrabold">Leadership Score · Feedback invitation</p>
            <p className="text-[11.5px] text-[var(--text-muted)] mt-0.5">
              One Meta-approved WhatsApp template, used for every company. Invitations cannot go out until Meta approves it.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={refreshStatus} disabled={!!busy}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-[var(--border)] text-[12px] font-bold text-[var(--text-main)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
              <RefreshCw size={13} className={busy === 'sync' ? 'animate-spin' : ''} />
              {busy === 'sync' ? 'Checking…' : 'Check status'}
            </button>
            {mayEdit && (
              <button type="button" onClick={() => setComposerOpen(true)}
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[12px] font-bold shadow-sm hover:opacity-90 transition-opacity">
                {template?.meta_template_name ? <Pencil size={13} /> : <Plus size={13} />}
                {template?.meta_template_name ? 'Edit template' : 'Create template'}
              </button>
            )}
          </div>
        </div>
      ) : (
      <DashboardHero icon={MessageCircle} title="Leadership Score — WhatsApp Template"
        subtitle="One invitation for every company. Write it, submit it to Meta, track its approval">
        <HeroButton icon={RefreshCw} onClick={refreshStatus}>
          {busy === 'sync' ? 'Checking…' : 'Check Status'}
        </HeroButton>
        {/* The page's primary action, so it sits with the other page-level controls rather
            than at the bottom of a section — writing the message is the first thing anyone
            comes here to do, and the only thing that has to happen before anything else can. */}
        {mayEdit && (
          <HeroButton icon={template?.meta_template_name ? Pencil : Plus}
            onClick={() => setComposerOpen(true)}>
            {template?.meta_template_name ? 'Edit Template' : 'Create Template'}
          </HeroButton>
        )}
      </DashboardHero>
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

      {loading ? (
        <Section title="WhatsApp Template" subtitle="Loading" icon={MessageCircle}>
          <div className="px-5 py-14 text-center text-[13px] font-bold text-[var(--text-muted)]">
            Loading template…
          </div>
        </Section>
      ) : (
        <>
          {/* ─── Approval status ─── */}
          <Section title="Approval Status" icon={FileCheck2}
            subtitle="Meta reviews every business-initiated template before it can be sent">
            <div className="px-5 py-4 space-y-3.5">
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <StatusPill value={status} />
                {/* Both actions need a template to act on. With nothing written the row is
                    empty rather than offering a Check that has nothing to check and a
                    Submit whose only outcome is "save the template first". */}
                {template?.meta_template_name && (
                  <div className="flex items-center gap-2">
                    <button type="button" onClick={refreshStatus} disabled={!!busy}
                      className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-[13px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors disabled:opacity-50">
                      <RefreshCw size={14} className={busy === 'sync' ? 'animate-spin' : ''} />
                      Check with Meta
                    </button>
                    {template?.can_submit && mayEdit && (
                      <button type="button" onClick={submit} disabled={!!busy}
                        title="Send this template to Meta for review"
                        className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[var(--accent-indigo)] text-white text-[13px] font-bold shadow-sm hover:opacity-90 transition-opacity disabled:opacity-40">
                        {busy === 'submit' ? <RefreshCw size={14} className="animate-spin" /> : <Send size={14} />}
                        {busy === 'submit' ? 'Submitting…' : 'Submit to Meta'}
                      </button>
                    )}
                  </div>
                )}
              </div>

              {/* What each state means for whether invitations can go out at all. */}
              {status === 'DRAFT' && (
                <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
                  Written here but never sent to Meta. <b className="text-[var(--text-main)]">No
                  invitations can go out</b> until it is submitted and approved.
                </p>
              )}
              {status === 'PENDING' && (
                <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-yellow-border)] bg-[var(--accent-yellow-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-yellow)]">
                  <Clock size={14} className="mt-[1px] shrink-0" />
                  <span>
                    With Meta for review — usually minutes to hours. Nothing polls for the
                    verdict, so press <b>Check with Meta</b> to pick it up. Invitations still
                    cannot be sent while it is pending.
                  </span>
                </div>
              )}
              {status === 'APPROVED' && (
                <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-green-border)] bg-[var(--accent-green-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-green)]">
                  <CheckCircle2 size={14} className="mt-[1px] shrink-0" />
                  <span>
                    Approved by Meta. Every company&rsquo;s invitations will be sent with it
                    {template?.active === false && ' — once you switch it on below'}.
                  </span>
                </div>
              )}
              {status === 'REJECTED' && (
                <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-red)]">
                  <XCircle size={14} className="mt-[1px] shrink-0" />
                  <span>
                    Meta rejected it{template?.rejected_reason ? `: ${template.rejected_reason}` : '.'}
                    {' '}Correct the wording below and submit again — the same template is
                    resubmitted, because a rejected name stays taken on your account.
                  </span>
                </div>
              )}

              {template?.last_submit_error && (
                <div className="flex items-start gap-2 rounded-xl border border-[var(--accent-red-border)] bg-[var(--accent-red-bg)] px-3.5 py-2.5 text-[12px] font-semibold text-[var(--accent-red)]">
                  <AlertTriangle size={14} className="mt-[1px] shrink-0" />
                  <span>Last submission failed: {template.last_submit_error}</span>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[11px] font-semibold text-[var(--text-muted)]">
                {template?.meta_template_id && (
                  <span>Meta id <span className="font-mono">{template.meta_template_id}</span></span>
                )}
                {stamp(template?.submitted_at) && <span>Submitted {stamp(template.submitted_at)}</span>}
                {stamp(template?.synced_at) && <span>Checked {stamp(template.synced_at)}</span>}
              </div>
            </div>
          </Section>

          {/* ─── The template itself ─── */}
          {/* Authored in the SHARED composer (components/whatsapp/TemplateComposer), the
              same modal TPMS and Notifications use: live WhatsApp preview, Meta's own
              validation rules, header/footer/buttons, and a payload you can read before an
              irreversible submit. Rebuilding a lesser version of it here would have meant
              two sets of rules to keep in step with Meta. */}
          <Section title="Message" icon={MessageCircle}
            subtitle={template?.meta_template_name
              // Meta's category, not ours. It decides how the message is paced and
              // whether it reaches someone who never opted in, so it belongs on the
              // line that identifies the template rather than two clicks away.
              ? `${template.meta_template_name} · ${template.language || 'en'}`
                + ` · ${template.meta_category || template.category || 'UTILITY'}`
              : 'Not written yet'}>
            <div className="px-5 py-4 space-y-3.5">
              {template?.meta_template_name ? (
                <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)] px-3.5 py-3">
                  <span className="block text-[10.5px] font-black uppercase tracking-wide text-[var(--text-muted)] mb-1.5">
                    What the recipient reads
                  </span>
                  <p className="text-[12.5px] font-medium whitespace-pre-wrap break-words">
                    {template.body || '—'}
                  </p>
                </div>
              ) : (
                <p className="text-[12.5px] font-semibold text-[var(--text-muted)]">
                  No invitation template written yet. Everything Meta needs — the wording,
                  header, buttons and category — is set in the composer.
                </p>
              )}

              {/* Fixed, not configurable. Every Leadership invitation says the same three
                  things, so the body is written to this order rather than each company
                  mapping it — a mapping whose only wrong answer looked completely correct. */}
              <div className="rounded-xl border border-[var(--border)] bg-[var(--input-bg)] px-3.5 py-3">
                <span className="block text-[10.5px] font-black uppercase tracking-wide text-[var(--text-muted)] mb-2">
                  Write the body using these
                </span>
                <div className="space-y-1.5">
                  {[
                    ['{{1}}', 'the person being asked for feedback'],
                    ['{{2}}', 'their feedback link — generated per invitation'],
                  ].map(([slot, meaning]) => (
                    <div key={slot} className="flex items-center gap-3">
                      <span className="font-mono text-[12px] font-bold text-[var(--accent-indigo)] w-12 shrink-0">
                        {slot}
                      </span>
                      <span className="text-[12px] font-semibold text-[var(--text-muted)]">{meaning}</span>
                    </div>
                  ))}
                </div>
                <p className="text-[11px] font-semibold text-[var(--text-muted)] mt-2.5 leading-relaxed">
                  Never paste a link into the template. Each giver gets a fresh single-use URL
                  minted when the invitation is sent, and {'{{2}}'} is where it lands — a fixed
                  link would send everyone to the same form.
                </p>
              </div>

              <span className="inline-flex items-center gap-1.5 text-[11.5px] font-semibold text-[var(--text-muted)]">
                <Info size={13} />
                {template?.is_ready
                  ? 'Approved — invitations will send with this.'
                  : 'Invitations cannot be sent until Meta approves this.'}
              </span>
            </div>
          </Section>

          {/* What actually happened to the messages this template sent. Placed last: the
              template above is the thing being configured, and this is the evidence that
              the configuration works. Deliberately carries no giver or leader name — the
              server strips them, so an administrator can see WHY a send failed without
              learning who was asked to rate whom. */}
          <Section title="WhatsApp log" icon={MessageCircle}
            subtitle="Recent send attempts. Delivery is reported by Meta, not by us.">
            <div className="px-5 py-4 flex flex-col gap-3">
              <div className="flex items-center gap-2 flex-wrap">
                {Object.entries(log?.counts || {}).map(([k, v]) => (
                  <span key={k}
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold border ${
                      LOG_TONE[k] === 'green'
                        ? 'text-[var(--accent-green)] bg-[var(--accent-green-bg)] border-[var(--accent-green-border)]'
                        : LOG_TONE[k] === 'red'
                        ? 'text-[var(--accent-red)] bg-[var(--accent-red-bg)] border-[var(--accent-red-border)]'
                        : LOG_TONE[k] === 'blue'
                        ? 'text-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] border-[var(--accent-indigo-border)]'
                        : 'text-[var(--text-muted)] bg-[var(--input-bg)] border-[var(--border)]'}`}>
                    {v} {k}
                  </span>
                ))}
                <button type="button" onClick={reloadLog}
                  className="ml-auto inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-bold text-[var(--text-muted)] border border-[var(--border)] hover:bg-[var(--input-bg)] transition-colors">
                  <RefreshCw size={11} /> Refresh
                </button>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-[12px]">
                  <thead>
                    <tr className="text-left text-[10.5px] font-black uppercase tracking-wide text-[var(--text-muted)]">
                      <th className="py-2 pr-4 font-black">When</th>
                      <th className="py-2 pr-4 font-black">Cycle</th>
                      <th className="py-2 pr-4 font-black">To</th>
                      <th className="py-2 pr-4 font-black">Status</th>
                      <th className="py-2 pr-4 font-black">Meta said</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(log?.rows || []).map((r) => (
                      <tr key={r.id} className="border-t border-[var(--border)] align-top">
                        <td className="py-2 pr-4 whitespace-nowrap text-[var(--text-muted)] font-semibold">
                          {stamp(r.at) || '—'}
                        </td>
                        <td className="py-2 pr-4 whitespace-nowrap font-mono text-[11px] text-[var(--text-muted)]">
                          {r.cycle || '—'}
                        </td>
                        <td className="py-2 pr-4 whitespace-nowrap font-mono text-[11px]">
                          {r.phone || '—'}
                        </td>
                        <td className="py-2 pr-4 whitespace-nowrap font-bold uppercase text-[10.5px]">
                          {r.status}
                          {r.attempts > 1 && (
                            <span className="ml-1 font-semibold text-[var(--text-muted)] normal-case">
                              ·{r.attempts} tries
                            </span>
                          )}
                        </td>
                        <td className="py-2 pr-4 text-[var(--text-muted)] font-semibold">
                          {r.error
                            || (r.message_status === 'held_for_quality_assessment'
                              ? 'Held for quality assessment — Meta will not deliver this.'
                              : r.message_status === 'accepted'
                                ? 'Accepted for delivery'
                                : r.message_id ? 'Accepted for delivery' : '—')}
                        </td>
                      </tr>
                    ))}
                    {!(log?.rows || []).length && (
                      <tr><td colSpan={5}
                        className="py-8 text-center text-[13px] font-bold text-[var(--text-muted)]">
                        Nothing sent yet.
                      </td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </Section>

        </>
      )}

      <AnimatePresence>
        {composerOpen && (
          <LeadershipTemplateModal
            template={template}
            api={templateApi}
            onClose={() => setComposerOpen(false)}
            onSaved={() => { setComposerOpen(false); reload(); }}
          />
        )}
      </AnimatePresence>
    </div>
  );
};

export default LeadershipWhatsApp;
