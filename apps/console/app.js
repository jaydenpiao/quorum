/* Quorum Operator Console.
 *
 * Plain browser JavaScript by design: no bundler, no framework, no
 * inline script. The console reads reduced state plus the event log,
 * derives operator-facing views, and keeps raw JSON available for
 * audit/debug workflows.
 */

'use strict';

var TOKEN_KEY = 'quorum.bearerToken';
var TIMELINE_LIMIT = 500;
var _state = null;
var _events = [];
var _selectedProposalId = null;
var _sseSource = null;

// -- DOM helpers ------------------------------------------------------------

function byId(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function setText(id, value) {
  var el = byId(id);
  if (el) {
    el.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  }
}

function setHtml(id, value) {
  var el = byId(id);
  if (el) {
    el.innerHTML = value;
  }
}

function formatTime(value) {
  if (!value) return '';
  var date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString([], {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function shortId(value) {
  if (!value) return '';
  return String(value).replace(/^([a-z]+_)([a-f0-9]{6}).*$/, '$1$2');
}

function shortDigest(value) {
  if (!value) return '';
  return String(value).replace(/^(sha256:[a-f0-9]{12}).*$/, '$1...');
}

function shortHash(value) {
  if (!value) return '';
  var text = String(value);
  return text.length > 16 ? text.slice(0, 16) + '...' : text;
}

function pill(label, kind) {
  return '<span class="pill ' + kind + '">' + escapeHtml(label) + '</span>';
}

function statusKind(value) {
  var status = String(value || '').toLowerCase();
  if (['executed', 'succeeded', 'approved', 'granted'].indexOf(status) >= 0) return 'success';
  if (['failed', 'blocked', 'denied', 'rollback_impossible', 'approval_denied'].indexOf(status) >= 0) {
    return 'danger';
  }
  if (['pending', 'started'].indexOf(status) >= 0) return 'warning';
  return 'neutral';
}

// -- auth + fetch -----------------------------------------------------------

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
    headers.Authorization = 'Bearer ' + token;
  }
  return headers;
}

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

// -- derived state ----------------------------------------------------------

function listValues(map) {
  if (!map) return [];
  return Object.keys(map).reduce(function (items, key) {
    return items.concat(map[key] || []);
  }, []);
}

function getPolicy(state, proposalId) {
  return (state.policy_decisions || {})[proposalId] || null;
}

function getVotes(state, proposalId) {
  return (state.votes || {})[proposalId] || [];
}

function getApprovals(state, proposalId) {
  return (state.human_approvals || {})[proposalId] || [];
}

function getExecutions(state, proposalId) {
  return (state.executions || {})[proposalId] || [];
}

function latest(items) {
  return items && items.length ? items[items.length - 1] : null;
}

function approvalLabel(approvals) {
  var decided = approvals.filter(function (entry) {
    return entry.decision === 'granted' || entry.decision === 'denied';
  });
  if (decided.length) return decided[decided.length - 1].decision;
  if (approvals.length) return 'pending';
  return 'not required';
}

function terminalProposal(proposal) {
  return ['executed', 'failed', 'rolled_back', 'blocked', 'rollback_impossible', 'approval_denied']
    .indexOf(proposal.status) >= 0;
}

function voteSummary(votes) {
  var approve = votes.filter(function (vote) { return vote.decision === 'approve'; }).length;
  var reject = votes.filter(function (vote) { return vote.decision === 'reject'; }).length;
  return approve + ' approve / ' + reject + ' reject';
}

function proposalById(state, proposalId) {
  return (state.proposals || []).filter(function (proposal) {
    return proposal.id === proposalId;
  })[0] || null;
}

// -- rendering --------------------------------------------------------------

function renderDashboard(state, events) {
  _state = state;
  _events = events || [];

  if (!_selectedProposalId || !proposalById(state, _selectedProposalId)) {
    _selectedProposalId = state.proposals && state.proposals.length ? state.proposals[0].id : null;
  }

  renderMetrics(state, events);
  renderProposals(state);
  renderImagePushes(state);
  renderTimeline(events);
  renderInspector(state);
  setText('raw-state', state);
  setText('raw-events', events);
}

function renderMetrics(state, events) {
  var proposals = state.proposals || [];
  var health = listValues(state.health_check_results);
  var passed = health.filter(function (check) { return check.passed; }).length;
  var pendingApprovals = proposals.filter(function (proposal) {
    return approvalLabel(getApprovals(state, proposal.id)) === 'pending';
  }).length;
  var newestIntent = state.intents && state.intents.length ? state.intents[state.intents.length - 1] : null;
  var openProposals = proposals.filter(function (proposal) {
    return !terminalProposal(proposal);
  }).length;

  setText('metric-environment', newestIntent ? newestIntent.environment : 'local');
  setText('metric-open-proposals', String(openProposals));
  setText('metric-pending-approvals', String(pendingApprovals));
  setText('metric-health', passed + '/' + health.length);
  setText('metric-events', (state.event_count || 0) + ' events');

  var last = events && events.length ? events[events.length - 1] : null;
  setText('last-hash', last && last.hash ? shortHash(last.hash) : 'no hash');
}

function renderProposals(state) {
  var proposals = state.proposals || [];
  setText('proposal-count', proposals.length);
  if (!proposals.length) {
    setHtml('proposal-rows', '<tr><td colspan="6" class="empty-state">No proposals yet.</td></tr>');
    return;
  }

  var rows = proposals.slice().reverse().map(function (proposal) {
    var votes = getVotes(state, proposal.id);
    var selected = proposal.id === _selectedProposalId ? ' selected' : '';
    return [
      '<tr class="' + selected + '" data-proposal-id="' + escapeHtml(proposal.id) + '">',
      '<td><div class="proposal-title"><strong>' + escapeHtml(proposal.title) + '</strong>',
      '<span class="muted mono">' + escapeHtml(shortId(proposal.id)) + '</span></div></td>',
      '<td>' + pill(proposal.action_type, 'info') + '</td>',
      '<td><span class="mono">' + escapeHtml(proposal.target) + '</span></td>',
      '<td>' + pill(proposal.risk, proposal.risk === 'high' || proposal.risk === 'critical' ? 'warning' : 'neutral') + '</td>',
      '<td>' + pill(proposal.status, statusKind(proposal.status)) + '</td>',
      '<td>' + escapeHtml(voteSummary(votes)) + '</td>',
      '</tr>',
    ].join('');
  }).join('');

  setHtml('proposal-rows', rows);
}

function renderImagePushes(state) {
  var pushes = state.image_pushes || [];
  if (!pushes.length) {
    setHtml('image-pushes', '<div class="empty-state">No image-push evidence yet.</div>');
    return;
  }

  var html = pushes.slice().reverse().map(function (push) {
    return [
      '<div class="evidence-item">',
      '<strong class="mono">' + escapeHtml(shortDigest(push.prod_digest)) + '</strong>',
      '<div class="evidence-meta">',
      '<span>commit ' + escapeHtml(String(push.commit_sha || '').slice(0, 7)) + '</span>',
      '<span>run ' + escapeHtml(push.workflow_run_id || '') + '</span>',
      '<span>reported by ' + escapeHtml(push.reported_by || '') + '</span>',
      '</div>',
      '<div class="muted mono">' + escapeHtml(push.prod_image_ref || '') + '</div>',
      '</div>',
    ].join('');
  }).join('');
  setHtml('image-pushes', html);
}

function renderTimeline(events) {
  if (!events || !events.length) {
    setHtml('events', '<div class="empty-state">No events yet.</div>');
    return;
  }

  var html = events.slice(-80).reverse().map(function (event) {
    return [
      '<div class="timeline-item">',
      '<div class="muted">' + escapeHtml(formatTime(event.ts)) + '</div>',
      '<div>',
      '<div class="timeline-type">' + escapeHtml(event.event_type) + '</div>',
      '<div class="muted mono">' + escapeHtml(shortId(event.entity_id)) + ' · ' + escapeHtml(shortHash(event.hash)) + '</div>',
      '</div>',
      '</div>',
    ].join('');
  }).join('');
  setHtml('events', html);
}

function renderInspector(state) {
  var proposal = proposalById(state, _selectedProposalId);
  if (!proposal) {
    setHtml('proposal-inspector', '<div class="inspector-empty">No proposal selected.</div>');
    fillSelectedProposalForms('');
    return;
  }

  var policy = getPolicy(state, proposal.id);
  var votes = getVotes(state, proposal.id);
  var approvals = getApprovals(state, proposal.id);
  var execution = latest(getExecutions(state, proposal.id));
  var checks = execution && execution.health_checks ? execution.health_checks : [];
  var result = execution && execution.result ? execution.result : {};
  var evidenceRefs = proposal.evidence_refs || [];

  fillSelectedProposalForms(proposal.id);

  var html = [
    '<div class="inspector-body">',
    '<div class="inspector-section">',
    '<div class="inspector-title"><strong>' + escapeHtml(proposal.title) + '</strong></div>',
    '<div>' + pill(proposal.status, statusKind(proposal.status)) + ' ' + pill(proposal.action_type, 'info') + '</div>',
    '</div>',
    '<div class="inspector-section kv-grid">',
    kv('Target', proposal.target),
    kv('Environment', proposal.environment),
    kv('Risk', proposal.risk),
    kv('Votes', voteSummary(votes)),
    kv('Policy', policy ? (policy.allowed ? 'allowed' : 'denied') : 'not evaluated'),
    kv('Human approval', approvalLabel(approvals)),
    kv('Execution', execution ? execution.status : 'not started'),
    kv('Released digest', shortDigest(result.released_image_digest)),
    kv('Previous digest', shortDigest(result.previous_image_digest)),
    '</div>',
    '<div class="inspector-section">',
    '<h3>Health checks</h3>',
    renderChecks(checks),
    '</div>',
    '<div class="inspector-section">',
    '<h3>Evidence refs</h3>',
    renderEvidenceRefs(evidenceRefs),
    '</div>',
    '</div>',
  ].join('');
  setHtml('proposal-inspector', html);
}

function kv(label, value) {
  return '<div class="kv-row"><span>' + escapeHtml(label) + '</span><span>' +
    escapeHtml(value || 'none') + '</span></div>';
}

function renderChecks(checks) {
  if (!checks || !checks.length) {
    return '<div class="muted">No health checks recorded.</div>';
  }
  return '<ul class="check-list">' + checks.map(function (check) {
    var mark = check.passed ? 'passed' : 'failed';
    return '<li>' + pill(mark, check.passed ? 'success' : 'danger') + ' ' +
      escapeHtml(check.name || '') + '</li>';
  }).join('') + '</ul>';
}

function renderEvidenceRefs(refs) {
  if (!refs || !refs.length) {
    return '<div class="muted">No evidence refs.</div>';
  }
  return '<ul class="evidence-refs">' + refs.map(function (ref) {
    return '<li class="mono">' + escapeHtml(ref) + '</li>';
  }).join('') + '</ul>';
}

function fillSelectedProposalForms(proposalId) {
  ['form-vote', 'form-approval'].forEach(function (formId) {
    var form = byId(formId);
    if (form && form.elements.proposal_id && proposalId) {
      form.elements.proposal_id.value = proposalId;
    }
  });
}

// -- data lifecycle ---------------------------------------------------------

async function loadState() {
  var state = await fetchJson('/api/v1/state');
  var events = await fetchJson('/api/v1/events');
  if (!state.ok || !events.ok) {
    return;
  }
  _events = (events.body || []).slice(-TIMELINE_LIMIT);
  renderDashboard(state.body, _events);
}

function setStatus(id, ok, message) {
  var el = byId(id);
  if (!el) return;
  el.textContent = message || '';
  el.className = 'status ' + (ok ? 'ok' : 'err');
}

function setStreamStatus(kind) {
  var el = byId('stream-status');
  if (!el) return;
  if (kind === 'live') {
    el.textContent = 'stream live';
    el.className = 'connection live';
  } else {
    el.textContent = 'stream disconnected';
    el.className = 'connection disconnected';
  }
}

function appendTimelineEvent(envelope) {
  _events.push(envelope);
  if (_events.length > TIMELINE_LIMIT) {
    _events.splice(0, _events.length - TIMELINE_LIMIT);
  }
  renderTimeline(_events);
  if (_events.length) {
    var last = _events[_events.length - 1];
    setText('last-hash', last && last.hash ? shortHash(last.hash) : 'no hash');
  }
}

function connectEventStream() {
  if (_sseSource) {
    _sseSource.close();
  }
  var source = new EventSource('/api/v1/events/stream');
  _sseSource = source;

  source.addEventListener('open', function () {
    setStreamStatus('live');
  });

  source.addEventListener('message', function (event) {
    try {
      var envelope = JSON.parse(event.data);
      appendTimelineEvent(envelope);
      if (/_created$|_approved$|_denied$|_completed$|_granted$|_impossible$|_succeeded$|_failed$/.test(envelope.event_type)) {
        loadState();
      }
    } catch (err) {
      console.warn('failed to parse SSE event', err, event.data);
    }
  });

  source.addEventListener('error', function () {
    setStreamStatus('disconnected');
  });
}

// -- forms ------------------------------------------------------------------

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
    setStatus('form-intent-status', true, 'created ' + shortId(result.body.id || ''));
    form.reset();
    form.elements.environment.value = 'local';
    await loadState();
  } else {
    var detail = (result.body && result.body.detail) || ('HTTP ' + result.status);
    setStatus('form-intent-status', false, 'rejected: ' + detail);
  }
}

async function submitVoteForm(event) {
  event.preventDefault();
  var data = readForm(event.target);
  var result = await postJson('/api/v1/votes', {
    proposal_id: data.proposal_id,
    decision: data.decision,
    reason: data.reason || '',
  });
  if (result.ok) {
    setStatus('form-vote-status', true, 'vote recorded');
    await loadState();
  } else {
    var detail = (result.body && result.body.detail) || ('HTTP ' + result.status);
    setStatus('form-vote-status', false, 'rejected: ' + detail);
  }
}

async function submitApprovalForm(event) {
  event.preventDefault();
  var data = readForm(event.target);
  var result = await postJson('/api/v1/approvals/' + encodeURIComponent(data.proposal_id), {
    decision: data.decision,
    reason: data.reason || '',
  });
  if (result.ok) {
    setStatus('form-approval-status', true, 'approval ' + data.decision);
    await loadState();
  } else {
    var detail = (result.body && result.body.detail) || ('HTTP ' + result.status);
    setStatus('form-approval-status', false, 'rejected: ' + detail);
  }
}

async function seedDemo() {
  var result = await postJson('/api/v1/demo/incident', {});
  if (!result.ok) {
    alert('demo seed failed: ' + ((result.body && result.body.detail) || result.status));
  }
  await loadState();
}

function selectProposal(id) {
  _selectedProposalId = id;
  if (_state) {
    renderProposals(_state);
    renderInspector(_state);
  }
}

document.addEventListener('DOMContentLoaded', function () {
  var tokenInput = byId('bearer-token');
  if (tokenInput) {
    tokenInput.value = getToken();
    tokenInput.addEventListener('input', function () {
      setToken(tokenInput.value.trim());
    });
  }

  byId('btn-seed').addEventListener('click', seedDemo);
  byId('btn-refresh').addEventListener('click', loadState);
  byId('form-intent').addEventListener('submit', submitIntentForm);
  byId('form-vote').addEventListener('submit', submitVoteForm);
  byId('form-approval').addEventListener('submit', submitApprovalForm);
  byId('proposal-rows').addEventListener('click', function (event) {
    var row = event.target.closest('tr[data-proposal-id]');
    if (row) {
      selectProposal(row.dataset.proposalId);
    }
  });

  loadState();
  connectEventStream();
});
