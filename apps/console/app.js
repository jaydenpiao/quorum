/* Quorum Operator Console — external script.
 *
 * Loaded via <script defer src="/console-static/app.js"></script>.
 *
 * Three concerns:
 *   1. Bearer-token management (localStorage — no cookies so CSRF is
 *      not a vector; the token input is the source of truth).
 *   2. Live event tail via EventSource on /api/v1/events/stream.
 *   3. Forms for the three mutating routes operators most need during
 *      the demo: create_intent, cast vote, grant/deny approval.
 *
 * Deliberate non-features: inline scripts (CSP blocks them), frameworks,
 * dependency bundler. Keep this file a plain-old browser-readable .js.
 */

'use strict';

var TOKEN_KEY = 'quorum.bearerToken';
var TIMELINE_LIMIT = 500; // cap memory; older events stay in /api/v1/events

// -- token management -------------------------------------------------------

function getToken() {
  return window.localStorage.getItem(TOKEN_KEY) || '';
}

function setToken(value) {
  if (value) {
    window.localStorage.setItem(TOKEN_KEY, value);
  } else {
    window.localStorage.removeItem(TOKEN_KEY);
  }
}

function authHeaders(extra) {
  var headers = extra || {};
  var token = getToken();
  if (token) {
    headers['Authorization'] = 'Bearer ' + token;
  }
  return headers;
}

// -- fetch wrappers ---------------------------------------------------------

async function fetchJson(path, options) {
  var opts = options || {};
  opts.headers = authHeaders(opts.headers || {});
  var res = await fetch(path, opts);
  var body = null;
  try {
    body = await res.json();
  } catch (_err) {
    body = null;
  }
  return { ok: res.ok, status: res.status, body: body };
}

async function postJson(path, payload) {
  return fetchJson(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  });
}

// -- rendering --------------------------------------------------------------

function setText(id, value) {
  var el = document.getElementById(id);
  if (el) {
    el.textContent = JSON.stringify(value, null, 2);
  }
}

function setStatus(id, ok, message) {
  var el = document.getElementById(id);
  if (!el) return;
  el.textContent = message || '';
  el.className = 'status ' + (ok ? 'ok' : 'err');
}

function setStreamStatus(kind) {
  var el = document.getElementById('stream-status');
  if (!el) return;
  if (kind === 'live') {
    el.textContent = 'stream: live';
    el.className = 'pill live';
  } else {
    el.textContent = 'stream: disconnected';
    el.className = 'pill disconnected';
  }
}

async function loadState() {
  var state = await fetchJson('/api/v1/state');
  var events = await fetchJson('/api/v1/events');
  if (!state.ok || !events.ok) {
    return;
  }
  var s = state.body;
  var evs = events.body || [];

  var approvalsTotal = 0;
  if (s.human_approvals) {
    Object.keys(s.human_approvals).forEach(function (k) {
      approvalsTotal += (s.human_approvals[k] || []).length;
    });
  }

  document.getElementById('summary').innerHTML =
    '<div class="pill">intents: ' + s.intents.length + '</div>' +
    '<div class="pill">findings: ' + s.findings.length + '</div>' +
    '<div class="pill">proposals: ' + s.proposals.length + '</div>' +
    '<div class="pill">approvals: ' + approvalsTotal + '</div>' +
    '<div class="pill">events: ' + s.event_count + '</div>';

  setText('intents', s.intents);
  setText('proposals', s.proposals);
  setText('policy', s.policy_decisions);
  setText('executions', s.executions);
  setText('rollbacks', s.rollbacks);
  setText('approvals', s.human_approvals || {});
  setText('events', evs.slice(-TIMELINE_LIMIT));
}

// -- SSE live tail ----------------------------------------------------------

var _sseSource = null;
var _timelineEvents = [];

function appendTimelineEvent(envelope) {
  _timelineEvents.push(envelope);
  if (_timelineEvents.length > TIMELINE_LIMIT) {
    _timelineEvents.splice(0, _timelineEvents.length - TIMELINE_LIMIT);
  }
  setText('events', _timelineEvents);
}

function connectEventStream() {
  if (_sseSource) {
    _sseSource.close();
  }
  // The SSE endpoint is public (same as GET /api/v1/events) so we don't
  // attach Authorization here — browsers don't let us anyway.
  var source = new EventSource('/api/v1/events/stream');
  _sseSource = source;

  source.addEventListener('open', function () {
    setStreamStatus('live');
  });

  source.addEventListener('message', function (event) {
    try {
      var envelope = JSON.parse(event.data);
      appendTimelineEvent(envelope);
      // Light-weight refresh of the state panels; the full GET /state
      // runs only on meaningful transitions, not on every event, so
      // idle ticks don't hammer the server.
      if (/_created$|_approved$|_denied$|_completed$|_granted$|_impossible$/.test(envelope.event_type)) {
        loadState();
      }
    } catch (err) {
      console.warn('failed to parse SSE event', err, event.data);
    }
  });

  source.addEventListener('error', function () {
    setStreamStatus('disconnected');
    // EventSource auto-reconnects; the onopen handler will flip the
    // status back to live when it recovers.
  });
}

// -- form handlers ----------------------------------------------------------

function readForm(form) {
  var data = {};
  Array.prototype.forEach.call(form.elements, function (el) {
    if (el.name) {
      data[el.name] = el.value;
    }
  });
  return data;
}

async function submitIntentForm(event) {
  event.preventDefault();
  var form = event.target;
  var data = readForm(form);
  var result = await postJson('/api/v1/intents', data);
  if (result.ok) {
    setStatus('form-intent-status', true, 'created intent ' + (result.body.id || ''));
    form.reset();
    form.elements['environment'].value = 'local';
    await loadState();
  } else {
    var detail = (result.body && result.body.detail) || ('HTTP ' + result.status);
    setStatus('form-intent-status', false, 'rejected: ' + detail);
  }
}

async function submitVoteForm(event) {
  event.preventDefault();
  var form = event.target;
  var data = readForm(form);
  var result = await postJson('/api/v1/votes', {
    proposal_id: data.proposal_id,
    decision: data.decision,
    reason: data.reason || '',
  });
  if (result.ok) {
    setStatus('form-vote-status', true, 'vote recorded on ' + data.proposal_id);
    await loadState();
  } else {
    var detail = (result.body && result.body.detail) || ('HTTP ' + result.status);
    setStatus('form-vote-status', false, 'rejected: ' + detail);
  }
}

async function submitApprovalForm(event) {
  event.preventDefault();
  var form = event.target;
  var data = readForm(form);
  var path = '/api/v1/approvals/' + encodeURIComponent(data.proposal_id);
  var result = await postJson(path, {
    decision: data.decision,
    reason: data.reason || '',
  });
  if (result.ok) {
    setStatus(
      'form-approval-status',
      true,
      'recorded ' + data.decision + ' approval on ' + data.proposal_id,
    );
    await loadState();
  } else {
    var detail = (result.body && result.body.detail) || ('HTTP ' + result.status);
    setStatus('form-approval-status', false, 'rejected: ' + detail);
  }
}

// -- lifecycle --------------------------------------------------------------

async function seedDemo() {
  var result = await postJson('/api/v1/demo/incident', {});
  if (!result.ok) {
    alert('demo seed failed: ' + (result.body && result.body.detail || result.status));
  }
  await loadState();
}

document.addEventListener('DOMContentLoaded', function () {
  // Hydrate token input from localStorage + persist edits.
  var tokenInput = document.getElementById('bearer-token');
  if (tokenInput) {
    tokenInput.value = getToken();
    tokenInput.addEventListener('change', function () {
      setToken(tokenInput.value.trim());
    });
  }

  document.getElementById('btn-seed').addEventListener('click', seedDemo);
  document.getElementById('btn-refresh').addEventListener('click', loadState);
  document.getElementById('form-intent').addEventListener('submit', submitIntentForm);
  document.getElementById('form-vote').addEventListener('submit', submitVoteForm);
  document.getElementById('form-approval').addEventListener('submit', submitApprovalForm);

  loadState();
  connectEventStream();
});
