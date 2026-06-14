// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function fmt$(v) { return v == null ? '—' : '$' + Number(v).toFixed(4); }
function fmtN(v) { return v == null ? '—' : Number(v).toLocaleString(); }
function fmtPct(v) { return v == null ? '—' : (Number(v) * 100).toFixed(1) + '%'; }
function fmtDur(v) { return v == null ? '—' : Number(v).toFixed(1) + 's'; }
function fmtDate(s) { return s ? s.replace('T', ' ').slice(0, 16) + ' UTC' : '—'; }

function badge(status) {
  const map = { success: 'badge-success', failed: 'badge-failed', partial: 'badge-partial',
                warning: 'badge-warning', critical: 'badge-critical', ok: 'badge-ok' };
  return `<span class="badge ${map[status] || ''}">${status}</span>`;
}

// ---------------------------------------------------------------------------
// Global summary
// ---------------------------------------------------------------------------

let _summaryData = null;
let _agentChart = null;
let _dailyChart = null;

function _todayStr() {
  return new Date().toISOString().slice(0, 10);
}

function _mtdStartStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`;
}

function applyDateRange() {
  const from = document.getElementById('date-from').value;
  const to = document.getElementById('date-to').value;
  loadSummary(from, to);
}

function resetDateRange() {
  document.getElementById('date-from').value = _mtdStartStr();
  document.getElementById('date-to').value = _todayStr();
  loadSummary();
}

async function loadSummary(from, to) {
  let url = '/api/summary';
  const params = new URLSearchParams();
  if (from) params.set('from', from);
  if (to) params.set('to', to);
  if (params.toString()) url += '?' + params.toString();
  const r = await fetch(url);
  const d = await r.json();
  _summaryData = d;

  document.getElementById('g-spend').textContent = fmt$(d.total_spend);
  document.getElementById('g-in').textContent = fmtN(d.total_input_tokens);
  document.getElementById('g-out').textContent = fmtN(d.total_output_tokens);
  document.getElementById('g-searches').textContent = fmtN(d.total_web_searches);
  document.getElementById('g-jobs').textContent = fmtN(d.total_jobs);
  document.getElementById('g-failed').textContent = fmtN(d.total_failed);

  renderAgentsTable(d);
  renderAgentChart(d);
  renderDailyChart(d);
  renderGlobalInsights(d);
}

function renderAgentsTable(d) {
  const tbody = document.getElementById('agents-tbody');
  tbody.innerHTML = [...d.agents].sort((a, b) => b.spend - a.spend).map(a => `
    <tr>
      <td><a href="/agent/${a.name}">${a.label}</a></td>
      <td>${fmt$(a.spend)}</td>
      <td>${fmtN(a.jobs)}</td>
      <td>${fmtN(a.failed)}</td>
      <td>${fmtN(a.web_searches)}</td>
      <td>${(d.run_frequency[a.name] || 0).toFixed(2)}</td>
      <td>${a.budget != null ? fmt$(a.budget) + '/mo' : '—'}</td>
      <td>${a.budget_status ? badge(a.budget_status) : '—'}</td>
    </tr>
  `).join('');
}

function renderAgentChart(d) {
  const sorted = [...d.agents].sort((a, b) => b.spend - a.spend);
  const labels = sorted.map(a => a.label);
  const values = sorted.map(a => +a.spend.toFixed(4));
  const ctx = document.getElementById('chart-by-agent').getContext('2d');
  if (_agentChart) _agentChart.destroy();
  _agentChart = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ label: 'MTD Spend ($)', data: values, backgroundColor: '#4a6cf7' }] },
    options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
  });
}

function renderDailyChart(d) {
  const labels = d.daily_spend.map(r => r.day);
  const values = d.daily_spend.map(r => +r.spend.toFixed(4));
  const ctx = document.getElementById('chart-daily').getContext('2d');
  if (_dailyChart) _dailyChart.destroy();
  _dailyChart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [{ label: 'Daily Spend ($)', data: values, borderColor: '#4a6cf7', fill: true, backgroundColor: 'rgba(74,108,247,.1)', tension: 0.3 }] },
    options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
  });
}

function renderGlobalInsights(d) {
  const agents = d.agents;
  const el = document.getElementById('insights-content');
  if (!agents.length) { el.textContent = 'No data yet.'; return; }

  const mostExpensive = [...agents].sort((a, b) => b.spend - a.spend)[0];
  const highestFail = [...agents].sort((a, b) => (b.failed / (b.jobs||1)) - (a.failed / (a.jobs||1)))[0];

  el.innerHTML = `
    <ul style="padding-left:18px;line-height:2">
      <li>Most expensive agent MTD: <strong>${mostExpensive.label}</strong> (${fmt$(mostExpensive.spend)})</li>
      <li>Highest failure rate: <strong>${highestFail.label}</strong> (${highestFail.jobs ? ((highestFail.failed/highestFail.jobs)*100).toFixed(0)+'%' : '—'})</li>
      <li>Total web search cost: <strong>${fmt$(d.total_web_searches * 0.01)}</strong> (${fmtN(d.total_web_searches)} searches × $0.01)</li>
    </ul>
  `;
}

// ---------------------------------------------------------------------------
// Agent drilldown
// ---------------------------------------------------------------------------

let _agentData = null;
let _allJobs = [];
let _sortKey = 'started_at';
let _sortAsc = false;

let _costTrendChart = null;
let _runFreqChart = null;
let _tokenBreakdownChart = null;

async function loadAgent(agentName) {
  const r = await fetch(`/api/agent/${agentName}`);
  _agentData = await r.json();
  const d = _agentData;

  document.getElementById('a-spend').textContent = fmt$(d.mtd.spend);
  document.getElementById('a-avg-cost').textContent = fmt$(d.agg.avg_cost);
  document.getElementById('a-duration').textContent = fmtDur(d.agg.avg_duration);
  document.getElementById('a-cache').textContent = fmtPct(d.agg.cache_hit_rate);
  document.getElementById('a-searches').textContent = Number(d.agg.avg_searches).toFixed(1);
  document.getElementById('a-success').textContent = fmtPct(d.agg.success_rate);
  document.getElementById('a-today').textContent = d.runs_today;
  document.getElementById('a-week').textContent = d.runs_week;
  document.getElementById('a-month').textContent = d.runs_month;

  // Budget
  if (d.budget != null) document.getElementById('budget-input').value = d.budget;
  if (d.budget_status) {
    document.getElementById('budget-status-badge').innerHTML = badge(d.budget_status);
    document.getElementById('budget-projected').textContent =
      `Projected: ${fmt$(d.projected)}/mo`;
  }

  // Bloat flag
  if (d.bloat_flag) document.getElementById('bloat-alert').style.display = 'block';

  renderCostTrend(d.cost_trend);
  renderRunFreq(d.run_freq);
  renderTokenBreakdown(d.token_breakdown);

  _allJobs = d.jobs;
  renderJobsTable(_allJobs);
}

function renderCostTrend(trend) {
  const ctx = document.getElementById('chart-cost-trend').getContext('2d');
  if (_costTrendChart) _costTrendChart.destroy();
  _costTrendChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: trend.map(r => r.day),
      datasets: [{ label: 'Avg Cost/Job ($)', data: trend.map(r => +r.avg_cost.toFixed(5)),
        borderColor: '#4a6cf7', fill: true, backgroundColor: 'rgba(74,108,247,.1)', tension: 0.3 }]
    },
    options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
  });
}

function renderRunFreq(freq) {
  const ctx = document.getElementById('chart-run-freq').getContext('2d');
  if (_runFreqChart) _runFreqChart.destroy();
  _runFreqChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: freq.map(r => r.day),
      datasets: [{ label: 'Jobs', data: freq.map(r => r.jobs), backgroundColor: '#6ee7b7' }]
    },
    options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } } }
  });
}

function renderTokenBreakdown(tb) {
  const ctx = document.getElementById('chart-token-breakdown').getContext('2d');
  if (_tokenBreakdownChart) _tokenBreakdownChart.destroy();
  if (!tb || !tb.total_in) return;
  _tokenBreakdownChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: ['Token Sources (est.)'],
      datasets: [
        { label: 'System Prompt*', data: [tb.sys || 0], backgroundColor: '#4a6cf7' },
        { label: 'Tool Results*',  data: [tb.tool || 0], backgroundColor: '#f59e0b' },
        { label: 'Conversation*',  data: [tb.conv || 0], backgroundColor: '#6ee7b7' },
      ]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      scales: { x: { stacked: true, beginAtZero: true }, y: { stacked: true } },
      plugins: { legend: { position: 'bottom' } }
    }
  });
}

// Jobs table

function renderJobsTable(jobs) {
  const tbody = document.getElementById('jobs-tbody');
  tbody.innerHTML = jobs.map(j => `
    <tr class="row-${j.status}">
      <td>${fmtDate(j.started_at)}</td>
      <td>${j.job_name}</td>
      <td>${fmtDur(j.duration_seconds)}</td>
      <td>${badge(j.status)}</td>
      <td>${fmtN(j.input_tokens)}</td>
      <td>${fmtN(j.output_tokens)}</td>
      <td>${fmtN(j.cache_read_tokens)}</td>
      <td>${fmtN(j.web_searches)}</td>
      <td>${fmt$(j.cost_total)}</td>
    </tr>
  `).join('');
}

function filterJobs() {
  const text = document.getElementById('filter-input').value.toLowerCase();
  const status = document.getElementById('filter-status').value;
  const filtered = _allJobs.filter(j =>
    (!text || j.job_name.toLowerCase().includes(text)) &&
    (!status || j.status === status)
  );
  renderJobsTable(filtered);
}

function sortBy(key) {
  if (_sortKey === key) _sortAsc = !_sortAsc;
  else { _sortKey = key; _sortAsc = true; }
  const sorted = [..._allJobs].sort((a, b) => {
    const av = a[key], bv = b[key];
    if (av == null) return 1; if (bv == null) return -1;
    return _sortAsc ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1);
  });
  renderJobsTable(sorted);
}

// Budget

async function saveBudget() {
  const budget = parseFloat(document.getElementById('budget-input').value);
  if (isNaN(budget)) return;
  await fetch(`/api/agent/${AGENT_NAME}/budget`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ budget }),
  });
  loadAgent(AGENT_NAME);
}

// Insights

async function refreshInsights() {
  const btn = document.getElementById('refresh-insights-btn');
  const el = document.getElementById('insights-content');
  btn.disabled = true;
  btn.textContent = 'Loading…';
  el.innerHTML = '<em>Calling Claude…</em>';
  try {
    const r = await fetch(`/api/agent/${AGENT_NAME}/insights`, { method: 'POST' });
    const d = await r.json();
    if (d.error) { el.innerHTML = `<span style="color:red">Error: ${d.error}</span>`; return; }
    el.innerHTML = d.insights.map(i => `
      <div class="insight-item">
        <span class="insight-severity sev-${i.severity}">${i.severity}</span>
        <div class="insight-text">
          <strong>${i.title}</strong>
          <span>${i.detail}</span>
        </div>
      </div>
    `).join('');
  } catch(e) {
    el.innerHTML = `<span style="color:red">Error: ${e.message}</span>`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Refresh';
  }
}

// ── Tab switching ──────────────────────────────────────────────────────────
function showTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === name);
  });
  document.getElementById('tab-dashboard').style.display = name === 'dashboard' ? '' : 'none';
  document.getElementById('tab-docs').style.display      = name === 'docs'      ? '' : 'none';
  document.getElementById('tab-amy').style.display       = name === 'amy'       ? '' : 'none';
  if (name === 'amy') loadAmy();
}

// ── Amy Performance Tab ────────────────────────────────────────────────────
let _amyScoreChart = null;
let _amyLoaded = false;

async function loadAmy() {
  if (_amyLoaded) return;
  _amyLoaded = true;
  try {
    const r = await fetch('/api/amy');
    const d = await r.json();
    renderAmyStats(d);
    renderAmyScoreChart(d);
    renderAmyMeetings(d);
    renderAmyScoreLog(d);
    renderAmyGuidelines(d);
    loadKb();
  } catch(e) {
    document.getElementById('amy-error').textContent = 'Failed to load: ' + e;
  }
}

function renderAmyStats(d) {
  document.getElementById('amy-drafts').textContent      = d.total_drafts ?? '—';
  document.getElementById('amy-meetings').textContent    = d.total_meetings ?? '—';
  document.getElementById('amy-avg-score').textContent   = d.avg_score != null ? d.avg_score.toFixed(1) + ' / 10' : '—';
  document.getElementById('amy-guidelines').textContent  = d.total_guidelines ?? '—';
  document.getElementById('amy-respond-runs').textContent = d.total_respond_runs ?? '—';
  document.getElementById('amy-mtd-cost').textContent    = d.mtd_cost != null ? '$' + d.mtd_cost.toFixed(2) : '—';
}

function renderAmyScoreChart(d) {
  const scores = d.scores_by_date || [];
  if (!scores.length) return;
  const ctx = document.getElementById('amy-score-chart').getContext('2d');
  if (_amyScoreChart) _amyScoreChart.destroy();
  _amyScoreChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: scores.map(s => s.date),
      datasets: [{
        label: 'Avg Score',
        data: scores.map(s => s.avg_score),
        borderColor: '#4a6cf7',
        backgroundColor: 'rgba(74,108,247,0.08)',
        tension: 0.3,
        pointRadius: 4,
        fill: true,
      }]
    },
    options: {
      responsive: true,
      scales: { y: { min: 0, max: 10, ticks: { stepSize: 2 } } },
      plugins: { legend: { display: false } }
    }
  });
}

function renderAmyMeetings(d) {
  const meetings = d.meetings || [];
  const tbody = document.getElementById('amy-meetings-tbody');
  if (!meetings.length) { tbody.innerHTML = '<tr><td colspan="3" style="color:#999;text-align:center">No meetings recorded yet</td></tr>'; return; }
  tbody.innerHTML = meetings.map(m => `
    <tr>
      <td>${m.date || '—'}</td>
      <td>${m.deal_name || '—'}</td>
      <td>${m.contact || '—'}</td>
    </tr>`).join('');
}

function renderAmyScoreLog(d) {
  const scores = d.score_log || [];
  const tbody = document.getElementById('amy-score-log-tbody');
  if (!scores.length) { tbody.innerHTML = '<tr><td colspan="3" style="color:#999;text-align:center">No scores recorded yet</td></tr>'; return; }
  tbody.innerHTML = scores.map(s => `
    <tr>
      <td>${s.date || '—'}</td>
      <td><strong>${s.score}</strong> / 10</td>
      <td style="color:#666;font-size:13px">${s.job_name || '—'}</td>
    </tr>`).join('');
}

function renderAmyGuidelines(d) {
  // kept for stat card count only — KB viewer handles content
}

// ── Amy KB Viewer ──────────────────────────────────────────────────────────
let _kbLoaded = false;
let _kbData = null;

async function loadKb() {
  if (_kbLoaded) return;
  _kbLoaded = true;
  try {
    const r = await fetch('/api/amy/kb');
    _kbData = await r.json();
    renderKbPanel('guidelines');
  } catch(e) {
    document.getElementById('kb-guidelines').textContent = 'Failed to load KB: ' + e;
  }
}

function showKb(name) {
  document.querySelectorAll('.kb-tab-btn').forEach((b, i) => {
    const names = ['guidelines', 'tov', 'threads', 'sources'];
    b.classList.toggle('active', names[i] === name);
  });
  ['guidelines', 'tov', 'threads', 'sources'].forEach(n => {
    document.getElementById('kb-' + n).style.display = n === name ? '' : 'none';
  });
  renderKbPanel(name);
}

function renderKbPanel(name) {
  if (!_kbData) return;
  const el = document.getElementById('kb-' + name);
  if (el.dataset.rendered) return;
  el.dataset.rendered = '1';

  if (name === 'guidelines' || name === 'tov') {
    const sections = _kbData[name === 'guidelines' ? 'guidelines' : 'tov'] || [];
    el.innerHTML = sections.map((s, i) => `
      <div class="kb-section">
        <div class="kb-section-header" onclick="toggleKbSection(this)">
          <span>${escHtml(s.title)}</span>
          <span style="display:flex;gap:12px;align-items:center">
            ${s.added_date ? `<span style="font-size:12px;color:#888;font-weight:400">${escHtml(s.added_date)}${s.added_by ? ' &nbsp;·&nbsp; ' + escHtml(s.added_by) : ''}</span>` : ''}
            <span class="kb-chevron">▶</span>
          </span>
        </div>
        <div class="kb-section-body">${escHtml(s.body)}</div>
      </div>`).join('') || '<p style="color:#999">Empty</p>';
  }

  if (name === 'threads') {
    const threads = _kbData.threads || [];
    el.innerHTML = threads.map((t, i) => `
      <div class="kb-section">
        <div class="kb-section-header" onclick="toggleKbSection(this)">
          <span>${escHtml(t.deal_name)}${t.contact ? ' &nbsp;·&nbsp; <span style="font-weight:400;color:#666">' + escHtml(t.contact) + '</span>' : ''}</span>
          <span style="display:flex;gap:12px;align-items:center">
            <span style="font-size:12px;color:#888;font-weight:400">${t.date || ''} &nbsp;·&nbsp; ${t.message_count} msgs &nbsp;·&nbsp; ${t.source === 'slack_training' ? '✍️ training' : '🔗 albato'}</span>
            <span class="kb-chevron">▶</span>
          </span>
        </div>
        <div class="kb-section-body">
          ${(t.messages || []).map(m => `
            <div class="kb-msg ${m.role}">
              <div class="kb-msg-label">${m.role === 'rep' ? '👤 Rep' : '📩 Lead'}</div>
              ${escHtml(m.text || '')}
            </div>`).join('')}
        </div>
      </div>`).join('') || '<p style="color:#999">No threads yet</p>';
  }

  if (name === 'sources') {
    const sources = _kbData.sources || [];
    el.innerHTML = sources.map(s => `
      <div class="kb-section">
        <div class="kb-section-header" onclick="toggleKbSection(this)">
          ${escHtml(s.title)}
          <span style="display:flex;gap:12px;align-items:center">
            <a href="${escHtml(s.url)}" target="_blank" style="font-size:12px;font-weight:400;color:#4a6cf7" onclick="event.stopPropagation()">↗ source</a>
            <span class="kb-chevron">▶</span>
          </span>
        </div>
        <div class="kb-section-body">${escHtml(s.text)}…</div>
      </div>`).join('') || '<p style="color:#999">No sources</p>';
  }
}

function toggleKbSection(header) {
  const body = header.nextElementSibling;
  const chevron = header.querySelector('.kb-chevron');
  body.classList.toggle('open');
  chevron.classList.toggle('open');
}

function escHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
