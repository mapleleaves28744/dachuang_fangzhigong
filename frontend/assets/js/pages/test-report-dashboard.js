(function () {
  const DATA_CANDIDATES = [
    'assets/data/test_dashboard_data.json',
    '../docs/testing/test_dashboard_data.json'
  ];

  function toNum(v, fallback) {
    const n = Number(v);
    return Number.isFinite(n) ? n : (fallback || 0);
  }

  function fmt(v, digits) {
    return toNum(v, 0).toFixed(typeof digits === 'number' ? digits : 2);
  }

  function riskClass(level) {
    const text = String(level || '').toLowerCase();
    if (text === 'high') return 'risk-high';
    if (text === 'medium') return 'risk-medium';
    return 'risk-low';
  }

  async function loadData() {
    let lastError = '';
    for (let i = 0; i < DATA_CANDIDATES.length; i += 1) {
      const path = DATA_CANDIDATES[i];
      try {
        const resp = await fetch(path, { cache: 'no-store' });
        if (!resp.ok) {
          lastError = 'HTTP ' + resp.status;
          continue;
        }
        const data = await resp.json();
        return data;
      } catch (err) {
        lastError = err && err.message ? err.message : String(err);
      }
    }
    throw new Error('无法加载测试数据: ' + lastError);
  }

  function renderMeta(meta) {
    const generated = document.getElementById('meta-generated-at');
    const version = document.getElementById('meta-version');
    if (generated) generated.textContent = meta && meta.generated_at ? meta.generated_at : '--';
    if (version) version.textContent = meta && meta.version ? meta.version : '--';
  }

  function renderKpi(kpi) {
    const grid = document.getElementById('kpi-grid');
    if (!grid) return;

    const cards = [
      ['pytest通过率', fmt(kpi.pytest_pass_rate_percent, 2) + '%'],
      ['E2E通过率', fmt(kpi.e2e_pass_rate_percent, 2) + '%'],
      ['并发峰值吞吐', fmt(kpi.concurrency_peak_rps, 2) + ' rps'],
      ['安全通过率', fmt(kpi.security_pass_rate_percent, 2) + '%'],
      ['可用性完成率', fmt(kpi.usability_completion_rate_percent, 2) + '%']
    ];

    grid.innerHTML = cards.map(function (item) {
      return '<article class="kpi-card">'
        + '<p class="kpi-title">' + item[0] + '</p>'
        + '<p class="kpi-value">' + item[1] + '</p>'
        + '</article>';
    }).join('');
  }

  function renderDimensions(dimensions) {
    const tbody = document.getElementById('dimension-table');
    if (!tbody) return;
    const rows = Array.isArray(dimensions) ? dimensions : [];
    tbody.innerHTML = rows.map(function (row) {
      return '<tr>'
        + '<td>' + (row.name || '--') + '</td>'
        + '<td>' + fmt(row.score, 1) + '</td>'
        + '<td class="' + riskClass(row.risk) + '">' + (row.risk || '--') + '</td>'
        + '<td>' + (row.summary || '--') + '</td>'
        + '</tr>';
    }).join('');
  }

  function renderPytestChart(rounds) {
    const chart = document.getElementById('pytest-chart');
    if (!chart) return;
    const data = Array.isArray(rounds) ? rounds : [];
    if (!data.length) {
      chart.innerHTML = '<p>暂无数据</p>';
      return;
    }

    const maxVal = Math.max.apply(null, data.map(function (x) { return toNum(x.duration_sec, 0); })) || 1;
    chart.innerHTML = data.map(function (row) {
      const val = toNum(row.duration_sec, 0);
      const h = Math.max(2, Math.round((val / maxVal) * 160));
      return '<div class="bar">'
        + '<span class="bar-value">' + fmt(val, 2) + 's</span>'
        + '<span class="bar-fill" style="height:' + h + 'px"></span>'
        + '<span class="bar-label">R' + (row.round || '-') + '</span>'
        + '</div>';
    }).join('');
  }

  function renderConcurrency(results) {
    const tbody = document.getElementById('concurrency-table');
    if (!tbody) return;
    const rows = Array.isArray(results) ? results : [];
    tbody.innerHTML = rows.map(function (row) {
      return '<tr>'
        + '<td>' + (row.scenario || '--') + '</td>'
        + '<td>' + toNum(row.workers, 0) + '</td>'
        + '<td>' + fmt(row.throughput_rps, 2) + '</td>'
        + '<td>' + fmt(row.latency_ms && row.latency_ms.p95, 2) + '</td>'
        + '<td>' + fmt(row.error_rate_percent, 2) + '</td>'
        + '<td class="' + (row.stable ? 'risk-low' : 'risk-high') + '">' + (row.stable ? 'stable' : 'unstable') + '</td>'
        + '</tr>';
    }).join('');
  }

  function renderSecurity(items) {
    const list = document.getElementById('security-list');
    if (!list) return;
    const rows = Array.isArray(items) ? items : [];
    list.innerHTML = rows.map(function (item) {
      return '<li>'
        + '<div class="security-head">'
        + '<strong>' + (item.name || '--') + '</strong>'
        + '<span class="' + riskClass(item.severity) + '">' + (item.severity || '--') + '</span>'
        + '</div>'
        + '<p class="security-detail">结果: ' + (item.passed ? 'PASS' : 'FAIL') + ' | ' + (item.detail || '') + '</p>'
        + '</li>';
    }).join('');
  }

  function renderUsability(results) {
    const tbody = document.getElementById('usability-table');
    if (!tbody) return;
    const rows = Array.isArray(results) ? results : [];
    tbody.innerHTML = rows.map(function (row) {
      return '<tr>'
        + '<td>' + (row.name || '--') + '</td>'
        + '<td class="' + (row.passed ? 'risk-low' : 'risk-high') + '">' + (row.passed ? 'PASS' : 'FAIL') + '</td>'
        + '<td>' + (row.status == null ? '--' : row.status) + '</td>'
        + '<td>' + fmt(row.latency_ms, 3) + '</td>'
        + '<td>' + (row.error_code || '--') + '</td>'
        + '</tr>';
    }).join('');
  }

  function renderSources(sources) {
    const list = document.getElementById('source-list');
    if (!list) return;
    const map = sources || {};
    const keys = Object.keys(map);
    list.innerHTML = keys.map(function (key) {
      return '<li>' + key + ': ' + map[key] + '</li>';
    }).join('');
  }

  function renderError(message) {
    const container = document.querySelector('#test-dashboard-page main');
    if (!container) return;
    container.innerHTML = '<section class="panel"><h2>数据加载失败</h2><p>' + message + '</p></section>';
  }

  async function boot() {
    try {
      const data = await loadData();
      renderMeta(data.meta || {});
      renderKpi(data.kpi || {});
      renderDimensions(data.dimensions || []);
      renderPytestChart((data.trends && data.trends.pytest_rounds) || []);
      renderConcurrency((data.trends && data.trends.concurrency) || []);
      renderSecurity((data.security && data.security.items) || []);
      renderUsability((data.usability && data.usability.results) || []);
      renderSources(data.sources || {});
    } catch (err) {
      renderError(err && err.message ? err.message : String(err));
    }
  }

  const refreshBtn = document.getElementById('btn-refresh');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', boot);
  }

  boot();
})();
