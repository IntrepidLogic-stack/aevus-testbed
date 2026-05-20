/**
 * Aevus Dashboard — RCA Narrative Panel
 *
 * Listens for messages on aevus/+/+/rca/+ topics (published by the
 * Bedrock RCA Lambda) and renders them as a slide-up panel.
 *
 * The patent-relevant demo:
 *   • A critical alarm fires on the Pi (sub-500ms via DNP3 unsolicited).
 *   • The RCA Lambda generates a narrative in <3s.
 *   • This panel renders the narrative the instant it arrives.
 *
 * Total visible latency from physical event → operator sees AI cause:
 * typically 2–4 seconds. Polling-only competitors can't match the
 * first half; LLM-blind operators can't match the second half.
 *
 * Brand compliance per CLAUDE.md / BRAND_SYSTEM_v2.md:
 *   • Display:  Manrope        → operator-facing copy
 *   • Numeric:  JetBrains Mono → latency value, confidence percentage
 *   • Status tokens (--status-bad/warn/good/info)
 *   • Inline SVG icons only, thin-line (strokeWidth 1.8)
 *
 * No emoji. No icon libraries. No external CSS beyond what the host
 * page already loads.
 */

(function () {
  'use strict';

  if (!window.AEVUS_MQTT) {
    console.warn('[Aevus RCA] window.AEVUS_MQTT not present — load mqtt-client.js first.');
    return;
  }

  // ── Inline styles (scoped via #aevus-rca-panel) ──────────────────────
  const STYLE = `
    #aevus-rca-panel {
      position: fixed;
      right: 24px;
      bottom: 24px;
      width: 460px;
      max-width: calc(100vw - 48px);
      background: #161E33;            /* --bg-card */
      border: 1px solid rgba(6,182,212,0.2);
      border-radius: 12px;
      box-shadow: 0 12px 40px rgba(0,0,0,0.45);
      color: #E5E7EB;
      font-family: 'Manrope', system-ui, sans-serif;
      font-size: 13px;
      line-height: 1.5;
      transform: translateY(calc(100% + 32px));
      transition: transform 0.32s cubic-bezier(0.2, 0.9, 0.32, 1);
      z-index: 9999;
      max-height: 70vh;
      display: flex;
      flex-direction: column;
    }
    #aevus-rca-panel.aevus-rca-visible {
      transform: translateY(0);
    }
    #aevus-rca-panel .aevus-rca-header {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 14px 16px 12px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
    }
    #aevus-rca-panel .aevus-rca-title {
      font-weight: 600;
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #06B6D4;                 /* --accent */
      flex: 1;
    }
    #aevus-rca-panel .aevus-rca-latency {
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 11px;
      color: #A78BFA;                 /* --status-unknown (informational) */
      padding: 3px 8px;
      border: 1px solid rgba(167,139,250,0.4);
      border-radius: 999px;
      letter-spacing: 0.04em;
    }
    #aevus-rca-panel .aevus-rca-close {
      background: transparent;
      border: 0;
      color: #9CA3AF;
      cursor: pointer;
      padding: 4px;
      display: flex;
      align-items: center;
    }
    #aevus-rca-panel .aevus-rca-close:hover { color: #E5E7EB; }
    #aevus-rca-panel .aevus-rca-body {
      padding: 14px 16px 16px;
      overflow-y: auto;
    }
    #aevus-rca-panel .aevus-rca-asset {
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 11px;
      color: #9CA3AF;
      margin-bottom: 8px;
    }
    #aevus-rca-panel .aevus-rca-cause {
      font-size: 14px;
      font-weight: 600;
      color: #F3F4F6;
      margin-bottom: 14px;
      line-height: 1.4;
    }
    #aevus-rca-panel .aevus-rca-section-label {
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #06B6D4;
      margin: 14px 0 6px;
    }
    #aevus-rca-panel .aevus-rca-evidence {
      list-style: none;
      padding-left: 0;
      margin: 0;
    }
    #aevus-rca-panel .aevus-rca-evidence li {
      position: relative;
      padding-left: 18px;
      margin-bottom: 6px;
      color: #D1D5DB;
    }
    #aevus-rca-panel .aevus-rca-evidence li::before {
      content: '';
      position: absolute;
      left: 4px;
      top: 8px;
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: #06B6D4;
    }
    #aevus-rca-panel .aevus-rca-action {
      background: rgba(6,182,212,0.06);
      border-left: 3px solid #06B6D4;
      padding: 10px 12px;
      border-radius: 0 6px 6px 0;
      color: #F3F4F6;
    }
    #aevus-rca-panel .aevus-rca-confidence {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-top: 16px;
      padding-top: 12px;
      border-top: 1px solid rgba(255,255,255,0.06);
    }
    #aevus-rca-panel .aevus-rca-confidence-bar {
      flex: 1;
      height: 6px;
      background: rgba(255,255,255,0.06);
      border-radius: 3px;
      overflow: hidden;
    }
    #aevus-rca-panel .aevus-rca-confidence-fill {
      height: 100%;
      transition: width 0.4s ease, background 0.4s ease;
    }
    #aevus-rca-panel .aevus-rca-confidence-value {
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 11px;
      min-width: 48px;
      text-align: right;
    }
    #aevus-rca-chip {
      position: fixed;
      right: 24px;
      bottom: 24px;
      background: #161E33;
      border: 1px solid rgba(6,182,212,0.4);
      border-radius: 999px;
      color: #06B6D4;
      font-family: 'Manrope', system-ui, sans-serif;
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.04em;
      padding: 8px 14px;
      cursor: pointer;
      display: none;
      align-items: center;
      gap: 8px;
      z-index: 9998;
      box-shadow: 0 4px 14px rgba(0,0,0,0.4);
    }
    #aevus-rca-chip.aevus-rca-chip-visible { display: flex; }
    #aevus-rca-chip .aevus-rca-chip-count {
      background: #06B6D4;
      color: #0B1020;
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 10px;
      padding: 2px 6px;
      border-radius: 999px;
    }
  `;

  // ── Mount DOM elements ──────────────────────────────────────────────
  function mount() {
    if (document.getElementById('aevus-rca-panel')) return;

    const style = document.createElement('style');
    style.id = 'aevus-rca-style';
    style.textContent = STYLE;
    document.head.appendChild(style);

    const panel = document.createElement('div');
    panel.id = 'aevus-rca-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Root cause analysis');
    panel.innerHTML = `
      <div class="aevus-rca-header">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
             stroke="#06B6D4" stroke-width="1.8" stroke-linecap="round"
             stroke-linejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="9"></circle>
          <path d="M12 3 a9 9 0 0 1 9 9 M12 8 v4 l3 2"></path>
        </svg>
        <div class="aevus-rca-title">AI Root Cause</div>
        <div class="aevus-rca-latency" aria-label="alert to narrative latency">—</div>
        <button class="aevus-rca-close" aria-label="Dismiss" type="button">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
               stroke-linejoin="round" aria-hidden="true">
            <path d="M18 6 L6 18 M6 6 L18 18"></path>
          </svg>
        </button>
      </div>
      <div class="aevus-rca-body">
        <div class="aevus-rca-asset" aria-label="alert identifier"></div>
        <div class="aevus-rca-cause"></div>
        <div class="aevus-rca-section-label">Evidence</div>
        <ul class="aevus-rca-evidence"></ul>
        <div class="aevus-rca-section-label">Recommended action</div>
        <div class="aevus-rca-action"></div>
        <div class="aevus-rca-confidence">
          <span style="font-size:10px;letter-spacing:0.1em;text-transform:uppercase;color:#06B6D4;font-weight:600;">Confidence</span>
          <div class="aevus-rca-confidence-bar">
            <div class="aevus-rca-confidence-fill" style="width:0%;background:#06B6D4;"></div>
          </div>
          <span class="aevus-rca-confidence-value">—</span>
        </div>
      </div>
    `;
    document.body.appendChild(panel);

    const chip = document.createElement('div');
    chip.id = 'aevus-rca-chip';
    chip.setAttribute('role', 'button');
    chip.setAttribute('tabindex', '0');
    chip.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
           stroke="#06B6D4" stroke-width="1.8" stroke-linecap="round"
           stroke-linejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9"></circle>
        <path d="M12 8 v4 l3 2"></path>
      </svg>
      <span>Latest RCA</span>
      <span class="aevus-rca-chip-count">1</span>
    `;
    document.body.appendChild(chip);

    panel.querySelector('.aevus-rca-close').addEventListener('click', hide);
    chip.addEventListener('click', show);
    chip.addEventListener('keypress', (e) => {
      if (e.key === 'Enter' || e.key === ' ') show();
    });
  }

  let autoHideTimer = null;
  let unreadCount = 0;
  let lastNarrative = null;

  function show() {
    const panel = document.getElementById('aevus-rca-panel');
    const chip = document.getElementById('aevus-rca-chip');
    if (!panel) return;
    panel.classList.add('aevus-rca-visible');
    chip.classList.remove('aevus-rca-chip-visible');
    unreadCount = 0;
    clearTimeout(autoHideTimer);
    autoHideTimer = setTimeout(() => {
      hide();
      if (lastNarrative) chip.classList.add('aevus-rca-chip-visible');
    }, 60_000);
  }

  function hide() {
    const panel = document.getElementById('aevus-rca-panel');
    const chip = document.getElementById('aevus-rca-chip');
    if (!panel) return;
    panel.classList.remove('aevus-rca-visible');
    clearTimeout(autoHideTimer);
    if (lastNarrative) chip.classList.add('aevus-rca-chip-visible');
  }

  // ── Render ──────────────────────────────────────────────────────────
  function render(envelope) {
    mount();
    const data = envelope || {};
    const rca = data.rca || {};
    const panel = document.getElementById('aevus-rca-panel');
    const chip = document.getElementById('aevus-rca-chip');
    if (!panel) return;

    const assetLine = `${data.asset_id || '?'}   ·   alert ${data.alert_id || '?'}`;
    panel.querySelector('.aevus-rca-asset').textContent = assetLine;
    panel.querySelector('.aevus-rca-cause').textContent =
      rca.probable_cause || '(no cause from RCA service)';

    const evidenceList = panel.querySelector('.aevus-rca-evidence');
    evidenceList.innerHTML = '';
    (rca.evidence || []).slice(0, 5).forEach((line) => {
      const li = document.createElement('li');
      li.textContent = line;
      evidenceList.appendChild(li);
    });

    panel.querySelector('.aevus-rca-action').textContent =
      rca.recommended_action || '(no recommendation)';

    // Confidence bar — color reflects threshold ranges from prompt.py.
    const conf = Math.max(0, Math.min(1, Number(rca.confidence || 0)));
    const confPct = (conf * 100).toFixed(0);
    const fill = panel.querySelector('.aevus-rca-confidence-fill');
    fill.style.width = confPct + '%';
    fill.style.background =
      conf >= 0.8 ? '#10D478' :   // --status-good
      conf >= 0.6 ? '#FBBF24' :   // --status-warn
                    '#EF4444';    // --status-bad
    panel.querySelector('.aevus-rca-confidence-value').textContent = confPct + '%';

    // Latency badge — the patent number.
    const lat = data.latency_ms_alert_to_rca;
    const latLabel = panel.querySelector('.aevus-rca-latency');
    if (lat != null) {
      latLabel.textContent = (lat >= 1000)
        ? `${(lat / 1000).toFixed(1)}s alert→RCA`
        : `${lat}ms alert→RCA`;
    } else {
      latLabel.textContent = 'alert→RCA';
    }

    lastNarrative = data;
    show();
    unreadCount = 0;
    chip.querySelector('.aevus-rca-chip-count').textContent = String(unreadCount || 1);
  }

  // ── Wire MQTT ───────────────────────────────────────────────────────
  window.AEVUS_MQTT.on('rca', (envelope) => {
    // The RCA Lambda publishes its full output as the message body —
    // not wrapped in the same envelope structure other publishers use,
    // because the Lambda doesn't go through src/integrations/.
    // Handle both shapes for forward-compat.
    const data = envelope.rca ? envelope : (envelope.payload || envelope);
    render(data);
  });

  // Expose for manual testing in the console:
  //   window.AEVUS_RCA.render({alert_id:'X', asset_id:'RTU-01', rca:{...}})
  window.AEVUS_RCA = { render, show, hide };
})();
