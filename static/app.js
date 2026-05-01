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

async function loadSummary() {
  const r = await fetch('/api/summary');
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
  tbody.innerHTML = d.agents.map(a => `
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
  const labels = d.agents.map(a => a.label);
  const values = d.agents.map(a => +a.spend.toFixed(4));
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
