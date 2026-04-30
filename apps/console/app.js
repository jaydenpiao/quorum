/* Quorum Operator Console.
 *
 * Plain browser JavaScript by design: no bundler, no framework, no
 * inline script. The console reads reduced state plus the event log,
 * derives operator-facing views, and keeps raw JSON available for
 * audit/debug workflows.
 */

'use strict';

var TOKEN_KEY = 'quorum.bearerToken';
var DEMO_TOKEN_FALLBACK = 'operator-key-dev';
var TIMELINE_LIMIT = 500;
var _state = null;
var _events = [];
var _selectedProposalId = null;
var _sseSource = null;
var _rootMeta = null;
var _chainVerification = null;

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

function proposalIdFromLocation() {
  var search = window.location && window.location.search ? window.location.search : '';
  if (!search) return null;
  try {
    var params = new URLSearchParams(search);
    var proposalId = params.get('proposal_id');
    return proposalId || null;
  } catch (_err) {
    return null;
  }
}

function updateSelectedProposalUrl(proposalId) {
  if (!proposalId || !window.location || !window.history || !window.history.replaceState) {
    return;
  }

  try {
    var url = new URL(window.location.href);
    url.searchParams.set('proposal_id', proposalId);
    if (!url.hash && window.location.hash) {
      url.hash = window.location.hash;
    }
    window.history.replaceState(null, '', url.pathname + url.search + url.hash);
  } catch (_err) {
    // URL state is a convenience for browser proof capture; rendering remains authoritative.
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

function ensureDemoToken() {
  var token = getToken();
  if (token) return token;

  var tokenInput = byId('bearer-token');
  token = tokenInput && tokenInput.value.trim()
    ? tokenInput.value.trim()
    : (tokenInput && tokenInput.placeholder) || DEMO_TOKEN_FALLBACK;

  if (tokenInput) {
    tokenInput.value = token;
  }
  setToken(token);
  return token;
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

function voteCountsForQuorum(vote) {
  return vote && vote.counted !== false;
}

function terminalProposal(proposal) {
  return ['executed', 'failed', 'rolled_back', 'blocked', 'rollback_impossible', 'approval_denied']
    .indexOf(proposal.status) >= 0;
}

function controlPlaneFlyApp() {
  var hostname = window.location && window.location.hostname ? window.location.hostname : '';
  var suffix = '.fly.dev';
  if (hostname.slice(-suffix.length) !== suffix) return '';
  return hostname.slice(0, -suffix.length);
}

function approvalCount(votes) {
  return votes.filter(function (vote) {
    return vote.decision === 'approve' && voteCountsForQuorum(vote);
  }).length;
}

function sameControlPlaneFlyDeploy(proposal) {
  var app = controlPlaneFlyApp();
  if (!app || proposal.action_type !== 'fly.deploy') return false;
  var target = proposal.target || (proposal.payload && proposal.payload.app) || '';
  return target === app;
}

function proposalActionability(state, proposal) {
  if (!proposal) {
    return { actionable: false, reason: 'select a proposal first' };
  }

  if (terminalProposal(proposal)) {
    return { actionable: false, reason: 'proposal is terminal: ' + proposal.status };
  }

  if (sameControlPlaneFlyDeploy(proposal)) {
    return {
      actionable: false,
      reason: 'fly.deploy targets same control-plane app: ' + controlPlaneFlyApp(),
    };
  }

  var policy = getPolicy(state, proposal.id);
  if (!policy) {
    return { actionable: false, reason: 'waiting for policy evaluation' };
  }

  if (!policy.allowed) {
    return { actionable: false, reason: 'policy denied proposal' };
  }

  var votes = getVotes(state, proposal.id);
  var requiredVotes = Number(policy.votes_required || 0);
  var approvedVotes = approvalCount(votes);
  if (approvedVotes < requiredVotes) {
    return {
      actionable: false,
      reason: 'waiting for quorum: ' + approvedVotes + '/' + requiredVotes + ' approvals',
    };
  }

  if (policy.requires_human && approvalLabel(getApprovals(state, proposal.id)) !== 'granted') {
    return { actionable: false, reason: 'waiting for human approval' };
  }

  if (proposal.status !== 'approved') {
    return { actionable: false, reason: 'proposal status is ' + proposal.status };
  }

  return { actionable: true, reason: 'actionable proposals can be executed' };
}

function voteSummary(votes) {
  var approve = approvalCount(votes);
  var reject = votes.filter(function (vote) {
    return vote.decision === 'reject' && voteCountsForQuorum(vote);
  }).length;
  var uncounted = votes.filter(function (vote) {
    return !voteCountsForQuorum(vote);
  }).length;
  var summary = approve + ' approve / ' + reject + ' reject';
  return uncounted ? summary + ' / ' + uncounted + ' not counted' : summary;
}

function proposalById(state, proposalId) {
  return (state.proposals || []).filter(function (proposal) {
    return proposal.id === proposalId;
  })[0] || null;
}

function rollbackByProposal(state, proposalId) {
  var records = (state.rollbacks || {})[proposalId] || [];
  return latest(records);
}

// -- rendering --------------------------------------------------------------

function renderDashboard(state, events) {
  _state = state;
  _events = events || [];

  var linkedProposalId = proposalIdFromLocation();
  if (linkedProposalId && proposalById(state, linkedProposalId)) {
    _selectedProposalId = linkedProposalId;
  } else if (!_selectedProposalId || !proposalById(state, _selectedProposalId)) {
    _selectedProposalId = state.proposals && state.proposals.length ? state.proposals[0].id : null;
  }

  renderMetrics(state, events);
  renderIntents(state);
  renderFindings(state);
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
  var actionableProposals = proposals.filter(function (proposal) {
    return proposalActionability(state, proposal).actionable;
  }).length;

  setText('metric-environment', newestIntent ? newestIntent.environment : 'local');
  setText('metric-open-proposals', String(openProposals));
  setText('metric-actionable-proposals', String(actionableProposals));
  setText('metric-pending-approvals', String(pendingApprovals));
  setText('metric-health', passed + '/' + health.length);
  setText('metric-events', (state.event_count || 0) + ' events');
  setText(
    'metric-chain-status',
    _chainVerification ? (_chainVerification.ok ? 'verified' : 'invalid') : 'unchecked'
  );

  var last = events && events.length ? events[events.length - 1] : null;
  if (_chainVerification && _chainVerification.last_hash) {
    setText('last-hash', shortHash(_chainVerification.last_hash));
  } else {
    setText('last-hash', last && last.hash ? shortHash(last.hash) : 'no hash');
  }
}

function renderIntents(state) {
  var intents = state.intents || [];
  if (!intents.length) {
    setHtml('intent-list', '<div class="empty-state">No intents yet.</div>');
    return;
  }

  var html = intents.slice().reverse().slice(0, 5).map(function (intent) {
    return [
      '<div class="signal-item">',
      '<strong>' + escapeHtml(intent.title) + '</strong>',
      '<div class="signal-meta">',
      '<span>' + escapeHtml(intent.environment || 'local') + '</span>',
      '<span>requested by ' + escapeHtml(intent.requested_by || 'operator') + '</span>',
      '<span>' + escapeHtml(formatTime(intent.created_at)) + '</span>',
      '</div>',
      '<div class="muted">' + escapeHtml(intent.description || '') + '</div>',
      '</div>',
    ].join('');
  }).join('');

  setHtml('intent-list', html);
}

function renderFindings(state) {
  var findings = state.findings || [];
  if (!findings.length) {
    setHtml('finding-list', '<div class="empty-state">No findings yet.</div>');
    return;
  }

  var html = findings.slice().reverse().slice(0, 6).map(function (finding) {
    var confidence = Math.round(Number(finding.confidence || 0) * 100);
    return [
      '<div class="signal-item">',
      '<strong>' + escapeHtml(finding.summary) + '</strong>',
      '<div class="signal-meta">',
      '<span>agent ' + escapeHtml(finding.agent_id || '') + '</span>',
      '<span>' + escapeHtml(shortId(finding.intent_id || '')) + '</span>',
      '<span>' + escapeHtml(confidence + '% confidence') + '</span>',
      '</div>',
      '</div>',
    ].join('');
  }).join('');

  setHtml('finding-list', html);
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
    var actionability = proposalActionability(state, proposal);
    var actionClass = actionability.actionable ? ' actionable' : ' not-actionable';
    return [
      '<tr class="' + selected + actionClass + '" title="' + escapeHtml(actionability.reason) + '" data-proposal-id="' + escapeHtml(proposal.id) + '">',
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
    updateExecuteActionability({ actionable: false, reason: 'select a proposal first' });
    return;
  }

  var policy = getPolicy(state, proposal.id);
  var votes = getVotes(state, proposal.id);
  var approvals = getApprovals(state, proposal.id);
  var execution = latest(getExecutions(state, proposal.id));
  var rollback = rollbackByProposal(state, proposal.id);
  var checks = execution && execution.health_checks ? execution.health_checks : [];
  var result = execution && execution.result ? execution.result : {};
  var evidenceRefs = proposal.evidence_refs || [];
  var actionability = proposalActionability(state, proposal);

  fillSelectedProposalForms(proposal.id);
  updateExecuteActionability(actionability);

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
    kv('Actionability', actionability.actionable ? 'ready' : actionability.reason),
    kv('Rollback', rollback ? (rollback.status || 'impossible') : 'none'),
    kv('Released digest', shortDigest(result.released_image_digest)),
    kv('Previous digest', shortDigest(result.previous_image_digest)),
    '</div>',
    '<div class="inspector-section">',
    '<h3>Votes</h3>',
    renderVotes(votes),
    '</div>',
    '<div class="inspector-section">',
    '<h3>Health checks</h3>',
    renderChecks(checks),
    '</div>',
    '<div class="inspector-section">',
    '<h3>Rollback details</h3>',
    renderRollback(rollback),
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

function voteSourceLabel(vote) {
  return vote.voter_kind === 'llm' ? 'llm-voter' : 'agent-voter';
}

function voteCountedLabel(vote) {
  if (vote.voter_kind === 'llm' && vote.counted === false) {
    return 'capped/non-counting LLM vote';
  }
  if (vote.voter_kind === 'llm') {
    return 'counted LLM vote';
  }
  return voteCountsForQuorum(vote) ? 'counted vote' : 'not counted vote';
}

function renderVotes(votes) {
  if (!votes || !votes.length) {
    return '<div class="muted">No votes recorded.</div>';
  }

  return '<div class="vote-list">' + votes.map(function (vote) {
    var isLlm = vote.voter_kind === 'llm';
    var counts = voteCountsForQuorum(vote);
    var classes = 'vote-card' + (isLlm ? ' vote-llm' : '') + (counts ? '' : ' vote-not-counted');
    var countKind = counts ? 'success' : 'warning';
    var metadata = [
      kv('Agent', vote.agent_id),
      kv('Source', voteSourceLabel(vote)),
      kv('Counted reason', vote.counted_reason || (counts ? 'legacy_counted' : 'not_counted')),
    ];

    if (isLlm) {
      metadata.push(kv('Model', vote.llm_model));
      metadata.push(kv('Prompt SHA-256', vote.system_prompt_sha256));
      metadata.push(kv('Observed cursor', vote.observed_event_cursor));
    }

    return [
      '<div class="' + classes + '">',
      '<div class="vote-header">',
      '<div>',
      '<strong>' + escapeHtml(vote.agent_id || 'unknown-agent') + '</strong>',
      '<div class="muted">' + escapeHtml(vote.reason || 'no rationale provided') + '</div>',
      '</div>',
      '<div class="vote-pills">',
      pill(vote.decision || 'unknown', vote.decision === 'approve' ? 'success' : 'danger'),
      pill(voteSourceLabel(vote), isLlm ? 'info' : 'neutral'),
      pill(voteCountedLabel(vote), countKind),
      '</div>',
      '</div>',
      '<div class="vote-meta">',
      metadata.join(''),
      '</div>',
      '</div>',
    ].join('');
  }).join('') + '</div>';
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

function renderRollback(rollback) {
  if (!rollback) {
    return '<div class="muted">No rollback activity recorded.</div>';
  }

  if (rollback.reason) {
    return '<ul class="evidence-refs">' +
      '<li>' + pill('impossible', 'danger') + ' ' + escapeHtml(rollback.reason) + '</li>' +
      '</ul>';
  }

  var steps = rollback.steps || [];
  if (!steps.length) {
    return '<div class="muted">Rollback recorded without explicit steps.</div>';
  }

  return '<ul class="evidence-refs">' + steps.map(function (step) {
    return '<li>' + escapeHtml(step) + '</li>';
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

function updateExecuteActionability(actionability) {
  var button = byId('btn-execute');
  var note = byId('execute-actionability');
  if (button) {
    button.disabled = !actionability.actionable;
  }
  if (note) {
    note.textContent = actionability.actionable
      ? 'selected proposal is approved and ready to execute'
      : actionability.reason;
  }
}

// -- data lifecycle ---------------------------------------------------------

async function loadState() {
  var results = await Promise.all([
    fetchJson('/api/v1/state'),
    fetchJson('/api/v1/events'),
    fetchJson('/'),
  ]);
  var state = results[0];
  var events = results[1];
  var root = results[2];
  if (!state.ok || !events.ok) {
    return;
  }
  if (root.ok && root.body) {
    _rootMeta = root.body;
    setText(
      'release-badge',
      (_rootMeta.display_version || ('version ' + (_rootMeta.version || 'unknown')))
    );
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

async function verifyEventChain() {
  var result = await fetchJson('/api/v1/events/verify');
  if (result.ok) {
    _chainVerification = result.body;
    setStatus('verify-status', true, 'event chain verified');
  } else {
    _chainVerification = { ok: false };
    var detail = (result.body && result.body.detail) || ('HTTP ' + result.status);
    setStatus('verify-status', false, 'verification failed: ' + detail);
  }
  if (_state) {
    renderMetrics(_state, _events);
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
  ensureDemoToken();
  var result = await postJson('/api/v1/demo/incident', {});
  if (!result.ok) {
    alert('demo seed failed: ' + ((result.body && result.body.detail) || result.status));
  }
  await loadState();
  await verifyEventChain();
}

async function executeSelectedProposal() {
  if (!_state || !_selectedProposalId) {
    setStatus('execute-status', false, 'select a proposal first');
    return;
  }

  var proposal = proposalById(_state, _selectedProposalId);
  var actionability = proposalActionability(_state, proposal);
  updateExecuteActionability(actionability);
  if (!actionability.actionable) {
    setStatus('execute-status', false, actionability.reason);
    return;
  }

  var result = await postJson(
    '/api/v1/proposals/' + encodeURIComponent(_selectedProposalId) + '/execute',
    { actor_id: 'operator' }
  );
  if (result.ok) {
    setStatus('execute-status', true, 'execution ' + (result.body.status || 'completed'));
  } else {
    var detail = (result.body && result.body.detail) || ('HTTP ' + result.status);
    setStatus('execute-status', false, 'rejected: ' + detail);
  }
  await loadState();
  await verifyEventChain();
}

function selectProposal(id) {
  _selectedProposalId = id;
  updateSelectedProposalUrl(id);
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
  byId('btn-verify-chain').addEventListener('click', verifyEventChain);
  byId('btn-execute').addEventListener('click', executeSelectedProposal);
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
  verifyEventChain();
  connectEventStream();
});
