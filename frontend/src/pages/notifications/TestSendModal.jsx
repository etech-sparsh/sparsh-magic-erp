import React, { useState } from 'react';
import { Send, CheckCircle2, AlertTriangle } from 'lucide-react';
import { testNotifyTemplate } from '../../services/notifyTemplatesApi';
import { Button, Field, Modal, ModalFooter, ModalHeader, Notice } from './NtUi';
import { bareSlug, errMsg, inputCls } from './ntConfig';

/**
 * Send one saved WhatsApp template to a real phone using its stored mapping.
 *
 * A success here means WhatsApp ACCEPTED the message — delivery is reported by Meta afterwards,
 * so the wording never claims the message arrived.
 */
const TestSendModal = ({ target, onClose }) => {
  const [phone, setPhone] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const run = async () => {
    setBusy(true);
    setResult(null);
    try {
      const res = await testNotifyTemplate({
        trigger: bareSlug(target.slug), scope: target.scope, company_id: target.company_id, phone,
      });
      setResult({
        ok: true,
        message: `WhatsApp accepted the message for ${res.data.sent_to}. Check the phone — each blank shows the name of the detail it carries.`,
      });
    } catch (e) {
      setResult({ ok: false, message: errMsg(e, 'Could not send the test.') });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal onClose={onClose} busy={busy} width="max-w-md" z="z-[60]">
      <ModalHeader icon={Send} tone="green" title="Send a test message" subtitle={target.meta_template_name}
        onClose={onClose} busy={busy} />
      <div className="px-5 py-4 space-y-3">
        <p className="text-[12.5px] text-[var(--text-muted)] leading-relaxed">
          Sends this template to one phone with its saved mapping, so a blank filled in the wrong
          order is easy to spot before a real person sees it.
        </p>
        <Field label="Phone number" required>
          <input type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="9876543210"
            className={inputCls} />
        </Field>
        {result && (
          <Notice tone={result.ok ? 'green' : 'red'} icon={result.ok ? CheckCircle2 : AlertTriangle}>
            {result.message}
          </Notice>
        )}
      </div>
      <ModalFooter>
        <Button variant="ghost" onClick={onClose} disabled={busy}>Close</Button>
        <Button icon={Send} busy={busy} disabled={!phone.trim()} onClick={run}>
          {busy ? 'Sending…' : 'Send test'}
        </Button>
      </ModalFooter>
    </Modal>
  );
};

export default TestSendModal;
