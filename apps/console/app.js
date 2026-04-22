/* Quorum Operator Console — external script (replaces inline <script> block).
 * Loaded via <script defer src="/console-static/app.js"></script>.
 * No framework. No secrets. Read-only console (Phase 1/2).
 */

async function fetchJson(path, options) {
  var res = await fetch(path, options || {});
  return await res.json();
}

async function seedDemo() {
  await fetchJson('/api/v1/demo/incident', { method: 'POST' });
  await loadState();
}

function setText(id, value) {
  document.getElementById(id).textContent = JSON.stringify(value, null, 2);
}

async function loadState() {
  var state = await fetchJson('/api/v1/state');
  var events = await fetchJson('/api/v1/events');

  document.getElementById('summary').innerHTML =
    '<div class="pill">intents: ' + state.intents.length + '</div>' +
    '<div class="pill">findings: ' + state.findings.length + '</div>' +
    '<div class="pill">proposals: ' + state.proposals.length + '</div>' +
    '<div class="pill">events: ' + state.event_count + '</div>';

  setText('intents', state.intents);
  setText('proposals', state.proposals);
  setText('policy', state.policy_decisions);
  setText('executions', state.executions);
  setText('rollbacks', state.rollbacks);
  setText('events', events);
}

// Wire up buttons via addEventListener — avoids inline onclick="" attributes,
// which would require 'unsafe-inline' in script-src under a strict CSP.
document.addEventListener('DOMContentLoaded', function () {
  document.getElementById('btn-seed').addEventListener('click', seedDemo);
  document.getElementById('btn-refresh').addEventListener('click', loadState);
  loadState();
});
