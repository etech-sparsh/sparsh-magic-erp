import React from 'react';
import { Clock, Eye, Pencil, Plus } from 'lucide-react';
import { Section } from '../../features/tpms/common/dashboardKit';
import { Button, Pill, Switch } from './NtUi';
import { MODULE_ICON, groupTriggers } from './ntConfig';

/* ─────────────────────────────────────────────────────────────
   One module's events on one channel — the Email and WhatsApp pages.

   Every event is listed, configured or not, so an admin reads the whole module at a glance:
   what it is, when it sends, and whether anything will actually go out.
   ───────────────────────────────────────────────────────────── */

const LIVE = ['sending', 'builtin', 'inheritedUnknown'];
const WARN = ['orange', 'red'];

const TriggerRow = ({ trigger, channel, state, scheduleText, canEdit, canToggle, onEdit, onPreview, onToggle }) => {
  const own = state.row;
  const effective = state.effective;
  const detail = channel === 'email'
    ? (effective?.subject ? `Subject: ${effective.subject}` : '')
    : (effective?.meta_template_name ? `Meta template: ${effective.meta_template_name}` : '');
  const note = WARN.includes(state.tone) || !detail ? state.hint : detail;
  const editLabel = own ? 'Edit'
    : (state.key === 'builtin' || state.key === 'inheritedUnknown' || state.inherited ? 'Customise' : 'Set up');

  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-3 px-5 py-3.5 border-t border-[var(--border)] hover:bg-[var(--table-hover)] transition-colors">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-[13.5px] font-extrabold">{trigger.label}</p>
          <Pill label={state.label} tone={state.tone} title={state.hint} />
        </div>
        <p className="text-[12px] text-[var(--text-muted)] mt-1 leading-relaxed">
          <span className="font-bold text-[var(--text-main)]">Sends when: </span>{trigger.description}
        </p>
        {scheduleText && (
          <p className="flex items-center gap-1.5 text-[11.5px] font-semibold text-[var(--accent-indigo)] mt-1">
            <Clock size={12} /> {scheduleText}
          </p>
        )}
        {note && (
          <p className="text-[11.5px] text-[var(--text-muted)] mt-1 truncate" title={note}>{note}</p>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {effective && (
          <Button variant="outline" size="sm" icon={Eye} onClick={() => onPreview(trigger, channel, effective)}>
            Preview
          </Button>
        )}
        {canEdit && (
          <Button variant={own ? 'outline' : 'primary'} size="sm" icon={own ? Pencil : Plus}
            onClick={() => onEdit(trigger, channel)}>
            {editLabel}
          </Button>
        )}
        {own && canToggle && (
          <Switch on={own.is_active !== false} onClick={() => onToggle(own, trigger, channel)} />
        )}
      </div>
    </div>
  );
};

const TriggerList = ({ module, channel, stateFor, scheduleText, canEdit, canToggle, onEdit, onPreview, onToggle }) => {
  const supported = module.triggers.filter((t) => (t.channels || ['email', 'whatsapp']).includes(channel));
  const hidden = module.triggers.length - supported.length;
  const live = supported.filter((t) => LIVE.includes(stateFor(module, t, channel).key)).length;
  const Icon = MODULE_ICON[module.key];

  return (
    <Section icon={Icon}
      title={`${module.label} · ${channel === 'whatsapp' ? 'WhatsApp' : 'Email'}`}
      subtitle={`${live} of ${supported.length} event${supported.length === 1 ? '' : 's'} sending`}>
      <p className="px-5 py-2.5 text-[12px] text-[var(--text-muted)] bg-[var(--input-bg)]">
        {module.description}
        {hidden > 0 && ` ${hidden} email-only event${hidden === 1 ? ' is' : 's are'} listed on the Email page.`}
      </p>
      {supported.length === 0 ? (
        <p className="px-5 py-10 text-center text-[12.5px] font-bold text-[var(--text-muted)] border-t border-[var(--border)]">
          No event in this module sends on {channel === 'whatsapp' ? 'WhatsApp' : 'email'}.
        </p>
      ) : groupTriggers(supported).map((bucket) => (
        <div key={bucket.name || 'all'}>
          {bucket.name && (
            <p className="px-5 pt-4 pb-2 text-[10.5px] font-black uppercase tracking-widest text-[var(--text-muted)] border-t border-[var(--border)]">
              {bucket.name}
            </p>
          )}
          {bucket.items.map((t) => (
            <TriggerRow key={t.slug} trigger={t} channel={channel} state={stateFor(module, t, channel)}
              scheduleText={scheduleText(t)} canEdit={canEdit} canToggle={canToggle}
              onEdit={onEdit} onPreview={onPreview} onToggle={onToggle} />
          ))}
        </div>
      ))}
    </Section>
  );
};

export default TriggerList;
