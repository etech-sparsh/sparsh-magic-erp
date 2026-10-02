import React, { useState } from 'react';
import { ArrowRight, Check, Zap } from 'lucide-react';
import { Button, Modal, ModalFooter, ModalHeader } from './NtUi';
import { CHANNEL_META, MODULE_ICON, groupTriggers } from './ntConfig';

/* ─────────────────────────────────────────────────────────────
   Trigger — pick the event a template is for: Module → Trigger (→ Channel).

   The Email and WhatsApp pages pass `lockedChannel`, so the choice is just "which event", and
   the step reads as one sentence: "When <trigger> happens, send <channel>".
   ───────────────────────────────────────────────────────────── */

const Step = ({ n, title, hint, done, children }) => (
  <section className="space-y-2.5">
    <div className="flex items-center gap-2.5">
      <span className={`w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-black shrink-0 ${
        done ? 'bg-[var(--accent-indigo)] text-white' : 'bg-[var(--input-bg)] text-[var(--text-muted)] border border-[var(--border)]'}`}>
        {done ? <Check size={12} /> : n}
      </span>
      <div className="min-w-0">
        <p className="text-[13px] font-extrabold leading-tight">{title}</p>
        {hint && <p className="text-[11px] text-[var(--text-muted)] mt-0.5">{hint}</p>}
      </div>
    </div>
    <div className="sm:pl-8">{children}</div>
  </section>
);

const CreateTemplateWizard = ({
  modules, initialModule, initialChannel = 'email', lockedChannel, statusFor, title, submitLabel,
  onClose, onContinue,
}) => {
  const [moduleKey, setModuleKey] = useState(
    () => (modules.some((m) => m.key === initialModule) ? initialModule : modules[0]?.key || ''),
  );
  const [slug, setSlug] = useState('');
  const [channel, setChannel] = useState(lockedChannel || initialChannel);

  const module = modules.find((m) => m.key === moduleKey) || null;
  const trigger = module?.triggers.find((t) => t.slug === slug) || null;
  const allowedChannels = lockedChannel
    ? [lockedChannel]
    : trigger
      ? (trigger.channels || ['email', 'whatsapp'])
      : (module?.external ? module.channels : ['email', 'whatsapp']);
  const chosenChannel = allowedChannels.includes(channel) ? channel : allowedChannels[0];
  const channelLabel = CHANNEL_META[chosenChannel]?.label || 'Email';

  const chooseModule = (key) => { setModuleKey(key); setSlug(''); };
  const hasTemplate = (t, ch) => !!(module && !module.external && statusFor && statusFor(module, t, ch)?.row);
  const badgeChannels = lockedChannel ? [lockedChannel] : ['email', 'whatsapp'];

  return (
    <Modal onClose={onClose} width="max-w-3xl">
      <ModalHeader icon={Zap} tone="orange"
        title={title || (lockedChannel ? `${channelLabel} template` : 'Set a template')}
        subtitle="Choose the module, then the trigger that should send it"
        onClose={onClose} />

      <div className="flex-1 overflow-y-auto px-5 py-5 space-y-6">
        <Step n={1} title="Module" hint="The part of the application the message belongs to." done={!!module}>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {modules.map((m) => {
              const Icon = MODULE_ICON[m.key];
              const active = m.key === moduleKey;
              return (
                <button key={m.key} type="button" onClick={() => chooseModule(m.key)}
                  className={`flex items-center gap-2.5 px-3 py-2.5 rounded-xl border text-left transition-all ${
                    active
                      ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)] text-[var(--accent-indigo)]'
                      : 'border-[var(--border)] hover:border-[var(--accent-indigo-border)]'}`}>
                  {Icon && <Icon size={16} className="shrink-0" />}
                  <span className="min-w-0">
                    <span className="block text-[12.5px] font-bold truncate">{m.label}</span>
                    <span className="block text-[10.5px] text-[var(--text-muted)]">
                      {m.triggers.length} trigger{m.triggers.length === 1 ? '' : 's'}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </Step>

        <Step n={2} title="Trigger" hint="What has to happen for this message to be sent." done={!!trigger}>
          {module ? (
            <div className="rounded-xl border border-[var(--border)] max-h-[320px] overflow-y-auto">
              {groupTriggers(module.triggers).map((bucket) => (
                <div key={bucket.name || 'all'}>
                  {bucket.name && (
                    <p className="sticky top-0 z-[1] px-3 py-1.5 text-[10px] font-black uppercase tracking-widest text-[var(--text-muted)] bg-[var(--bg-card)] border-b border-[var(--border)]">
                      {bucket.name}
                    </p>
                  )}
                  {bucket.items.map((t) => {
                    const active = t.slug === slug;
                    return (
                      <button key={t.slug} type="button" onClick={() => setSlug(t.slug)}
                        className={`w-full flex items-start gap-2.5 px-3 py-2.5 text-left border-b border-[var(--border)] last:border-b-0 transition-colors ${
                          active ? 'bg-[var(--accent-indigo-bg)]' : 'hover:bg-[var(--input-bg)]'}`}>
                        <span className={`mt-0.5 w-4 h-4 rounded-full border flex items-center justify-center shrink-0 ${
                          active ? 'bg-[var(--accent-indigo)] border-[var(--accent-indigo)] text-white' : 'border-[var(--border)]'}`}>
                          {active && <Check size={10} />}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-1.5">
                            <span className="text-[12.5px] font-bold">{t.label}</span>
                            {badgeChannels.filter((ch) => hasTemplate(t, ch)).map((ch) => (
                              <span key={ch}
                                className="text-[9.5px] font-black uppercase tracking-wide px-1.5 py-0.5 rounded bg-[var(--accent-green-bg)] text-[var(--accent-green)]">
                                {lockedChannel ? 'Template set ✓' : `${CHANNEL_META[ch].label} ✓`}
                              </span>
                            ))}
                          </span>
                          <span className="block text-[11.5px] text-[var(--text-muted)] mt-0.5 leading-snug">{t.description}</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-[12px] text-[var(--text-muted)]">Choose a module first.</p>
          )}
        </Step>

        {!lockedChannel && (
          <Step n={3} title="Channel" hint="How the message reaches people." done={!!trigger}>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {['email', 'whatsapp'].map((ch) => {
                const meta = CHANNEL_META[ch];
                const Icon = meta.icon;
                const ok = allowedChannels.includes(ch);
                const active = ok && chosenChannel === ch;
                const isWa = ch === 'whatsapp';
                return (
                  <button key={ch} type="button" disabled={!ok} onClick={() => setChannel(ch)}
                    className={`flex items-center gap-2.5 px-3.5 py-3 rounded-xl border text-left transition-all disabled:opacity-45 disabled:cursor-not-allowed ${
                      active
                        ? 'border-[var(--accent-indigo)] bg-[var(--accent-indigo-bg)]'
                        : 'border-[var(--border)] enabled:hover:border-[var(--accent-indigo-border)]'}`}>
                    <span className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                      style={{
                        background: isWa ? 'var(--accent-green-bg)' : 'var(--accent-indigo-bg)',
                        color: isWa ? 'var(--accent-green)' : 'var(--accent-indigo)',
                      }}>
                      <Icon size={16} />
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[13px] font-bold">{meta.label}</span>
                      <span className="block text-[10.5px] text-[var(--text-muted)]">
                        {!ok ? 'Not used by this trigger' : isWa ? 'Uses a Meta-approved template' : 'Subject and message'}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </Step>
        )}
      </div>

      <ModalFooter>
        <p className="mr-auto text-[12px] text-[var(--text-muted)] min-w-0">
          {trigger
            ? <>When <b className="text-[var(--text-main)]">{trigger.label}</b> happens, send {chosenChannel === 'whatsapp' ? 'a WhatsApp message' : 'an email'}.</>
            : 'Choose a module and a trigger.'}
        </p>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button icon={ArrowRight} disabled={!trigger}
          onClick={() => onContinue({ moduleKey, trigger, channel: chosenChannel })}>
          {submitLabel || 'Set template'}
        </Button>
      </ModalFooter>
    </Modal>
  );
};

export default CreateTemplateWizard;
