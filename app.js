(function () {
  'use strict';

  // 数据由 fetch.py 生成，字段结构见 data/latest.json
  fetch('data/latest.json?_=' + Date.now())
    .then(function (resp) {
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      return resp.json();
    })
    .then(function (data) {
      document.getElementById('loading').classList.add('hidden');
      document.getElementById('content').classList.remove('hidden');
      render(data);
    })
    .catch(function (err) {
      document.getElementById('loading').classList.add('hidden');
      var el = document.getElementById('error');
      el.textContent = '数据加载失败（' + err.message + '），请稍后刷新重试。';
      el.classList.remove('hidden');
    });

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // legends[].level 是字符串（"1"-"5"），站点/预报里的 level 是整数，统一用 String() 查表
  function buildLegendMap(data) {
    var map = {};
    (data.legends || []).forEach(function (lg) { map[String(lg.level)] = lg; });
    return map;
  }

  function legendOf(legendMap, level) {
    return legendMap[String(level)] || { level: String(level), chLevel: '未知', color: '#eeeeee', description: '' };
  }

  // "2026-09-10T22:10:48+08:00" -> "2026-09-10 22:10:48"，数据时间均为北京时间，直接展示
  function fmtIso(s) {
    return s ? String(s).replace('T', ' ').replace(/\+.*$/, '') : '-';
  }

  var WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

  // "2026-09-11" -> "9月11日 周五"
  function fmtDate(s) {
    var parts = String(s || '').split('-');
    if (parts.length !== 3) return esc(s);
    var y = +parts[0], m = +parts[1], d = +parts[2];
    if (!y || !m || !d) return esc(s);
    var wd = WEEKDAYS[new Date(y, m - 1, d).getDay()];
    return m + '月' + d + '日 ' + wd;
  }

  function render(data) {
    var legendMap = buildLegendMap(data);
    renderOverview(data, legendMap);
    renderGrid(data, legendMap);
    renderForecast(data, legendMap);
    renderLegend(data);
  }

  /* ---------- 全市概况 ---------- */
  function renderOverview(data, legendMap) {
    var cw = data.citywide || {};
    var lg = legendOf(legendMap, cw.level);
    document.getElementById('overview').innerHTML =
      '<div class="overview-badge" style="background:' + esc(lg.color) + '">' +
        '<div class="overview-level">' + esc(cw.levelText || lg.chLevel) + '</div>' +
        '<div class="overview-sub">全市花粉等级 ' + esc(cw.level) + ' 级</div>' +
      '</div>' +
      '<div class="overview-meta">' +
        '<span>全市平均浓度 <b>' + esc(cw.avgValue == null ? '-' : cw.avgValue) + '</b></span>' +
        '<span>观测时间 <b>' + esc(cw.obsTime || '-') + '</b></span>' +
        '<span>数据更新 <b>' + esc(fmtIso(data.updatedAt)) + '</b></span>' +
      '</div>' +
      '<p class="advice">' + esc(cw.advice || '') + '</p>';
  }

  /* ---------- 16区网格 + 趋势图联动 ---------- */
  var currentData = null;
  var currentLegendMap = null;
  var selectedStaId = null;

  function renderGrid(data, legendMap) {
    currentData = data;
    currentLegendMap = legendMap;
    var stations = data.stations || [];
    // 默认选中当前等级最高的站点
    var def = stations.reduce(function (a, b) {
      return (b.level || 0) > ((a && a.level) || 0) ? b : a;
    }, null);
    selectedStaId = def ? def.staId : null;

    var grid = document.getElementById('district-grid');
    grid.innerHTML = '';
    stations.forEach(function (st) {
      var lg = legendOf(legendMap, st.level);
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'district';
      btn.style.background = lg.color;
      btn.dataset.staId = st.staId;
      btn.innerHTML =
        '<span class="d-name">' + esc(st.staName) + '</span>' +
        '<span class="d-level">' + esc(lg.chLevel) + '（' + esc(st.level) + ' 级）</span>' +
        '<span class="d-value">浓度 ' + esc(st.value == null ? '-' : st.value) + ' · ' + esc((st.time || '').slice(11, 16)) + '</span>';
      btn.addEventListener('click', function () { selectStation(st.staId); });
      grid.appendChild(btn);
    });
    markSelected();
    renderChart();
  }

  function selectStation(staId) {
    selectedStaId = staId;
    markSelected();
    renderChart();
  }

  function markSelected() {
    var nodes = document.querySelectorAll('.district');
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].classList.toggle('selected', nodes[i].dataset.staId === selectedStaId);
    }
  }

  /* ---------- 24 小时趋势：纯 SVG ---------- */
  function renderChart() {
    var chartEl = document.getElementById('chart');
    var adviceEl = document.getElementById('chart-advice');
    var station = (currentData.stations || []).filter(function (st) {
      return st.staId === selectedStaId;
    })[0];
    if (!station) { chartEl.innerHTML = '<p class="notice">暂无站点数据</p>'; return; }

    document.getElementById('chart-title').textContent = station.staName + ' · 24 小时逐时趋势';
    var rows = ((currentData.histories || {})[station.staId] || []).filter(function (r) {
      return typeof r.value === 'number' && r.time;
    });
    if (!rows.length) {
      chartEl.innerHTML = '<p class="notice">该站点暂无 24 小时历史数据</p>';
      adviceEl.textContent = '';
      return;
    }

    var last = rows[rows.length - 1];
    adviceEl.textContent = last.advice ? ('最新防护建议：' + last.advice) : '';

    var W = 720, H = 260;
    var padL = 36, padR = 14, padT = 16, padB = 34;
    var iw = W - padL - padR, ih = H - padT - padB;
    var n = rows.length;
    var maxV = Math.max.apply(null, rows.map(function (r) { return r.value; }));
    var yMax = Math.max(5, Math.ceil(maxV * 1.25));

    function x(i) { return padL + (n === 1 ? iw / 2 : iw * i / (n - 1)); }
    function y(v) { return padT + ih * (1 - v / yMax); }

    var s = [];
    s.push('<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="24小时花粉浓度趋势图">');

    // 等级背景色带：每个观测时点一条竖带，按当时等级着色
    var band = iw / n;
    rows.forEach(function (r, i) {
      var lg = legendOf(currentLegendMap, r.level);
      var bx = Math.max(padL, Math.min(x(i) - band / 2, W - padR - band));
      s.push('<rect x="' + bx.toFixed(1) + '" y="' + padT + '" width="' + (band + 0.5).toFixed(1) +
        '" height="' + ih + '" fill="' + esc(lg.color) + '"/>');
    });

    // 横向网格线与纵轴刻度
    var ticks = 4;
    for (var t = 0; t <= ticks; t++) {
      var v = yMax * t / ticks;
      var gy = y(v);
      s.push('<line x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) + '" y2="' + gy +
        '" stroke="#eadfe4" stroke-width="1"/>');
      s.push('<text x="' + (padL - 6) + '" y="' + (gy + 4) + '" text-anchor="end" font-size="11" fill="#9b8290">' +
        Math.round(v) + '</text>');
    }

    // 折线与数据点
    var pts = rows.map(function (r, i) { return x(i).toFixed(1) + ',' + y(r.value).toFixed(1); });
    s.push('<polyline points="' + pts.join(' ') + '" fill="none" stroke="#b03060" stroke-width="2" stroke-linejoin="round"/>');
    rows.forEach(function (r, i) {
      var lg = legendOf(currentLegendMap, r.level);
      s.push('<circle cx="' + x(i).toFixed(1) + '" cy="' + y(r.value).toFixed(1) + '" r="3.2" fill="#b03060">' +
        '<title>' + esc(r.time) + '｜浓度 ' + r.value + '｜' + esc(lg.chLevel) + '（' + r.level + ' 级）</title></circle>');
    });

    // 横轴时间标签（"2026-09-10 21:00:00" -> "21:00"），首尾必标，中间每隔3小时
    rows.forEach(function (r, i) {
      if (i !== 0 && i !== n - 1 && i % 3 !== 0) return;
      s.push('<text x="' + x(i).toFixed(1) + '" y="' + (H - 12) + '" text-anchor="middle" font-size="11" fill="#9b8290">' +
        esc(r.time.slice(11, 16)) + '</text>');
    });

    s.push('</svg>');
    chartEl.innerHTML = s.join('');
  }

  /* ---------- 分区预报 ---------- */
  function renderForecast(data, legendMap) {
    var box = document.getElementById('forecast');
    var days = data.forecast || [];
    if (!days.length) { box.innerHTML = '<p class="notice">暂无预报数据</p>'; return; }

    box.innerHTML = days.map(function (day) {
      var areas = day.areas || [];
      var lvls = areas.map(function (a) { return a.level; }).filter(function (v) {
        return typeof v === 'number';
      });
      var overall = lvls.length
        ? Math.round(lvls.reduce(function (a, b) { return a + b; }, 0) / lvls.length)
        : null;
      var lg = legendOf(legendMap, overall);

      var chips = areas.map(function (a) {
        var alg = legendOf(legendMap, a.level);
        return '<span class="forecast-area" style="background:' + esc(alg.color) + '">' +
          '<span>' + esc(a.areaName) + '</span>' +
          '<span class="fa-level">' + esc(alg.chLevel) + '</span></span>';
      }).join('');

      return '<div class="forecast-day">' +
        '<div class="forecast-head">' +
          '<span class="forecast-date">' + fmtDate(day.date) + '</span>' +
          '<span class="forecast-overall" style="background:' + esc(lg.color) + '">全市约 ' +
            esc(lg.chLevel) + '（' + esc(overall == null ? '-' : overall) + ' 级）</span>' +
        '</div>' +
        '<div class="forecast-areas">' + chips + '</div>' +
      '</div>';
    }).join('');
  }

  /* ---------- 等级图例 ---------- */
  function renderLegend(data) {
    var box = document.getElementById('legend');
    var legends = (data.legends || []).slice().sort(function (a, b) {
      return (+a.level) - (+b.level);
    });
    if (!legends.length) { box.innerHTML = '<p class="notice">暂无图例数据</p>'; return; }

    box.innerHTML = legends.map(function (lg) {
      var range = (typeof lg.maxValue === 'number' && lg.maxValue >= 99999)
        ? lg.minValue + ' 以上'
        : lg.minValue + ' – ' + lg.maxValue;
      return '<div class="legend-item">' +
        '<span class="legend-swatch" style="background:' + esc(lg.color) + '">' + esc(lg.chLevel) + '</span>' +
        '<div class="legend-body">' +
          '<div class="legend-range">' + esc(lg.level) + ' 级 · 浓度区间 ' + esc(range) + '</div>' +
          '<div class="legend-desc">' + esc(lg.description) + '</div>' +
        '</div>' +
      '</div>';
    }).join('');
  }
})();
