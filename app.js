(function () {
  'use strict';

  /* ==================== i18n ==================== */

  var I18N = {
    zh: {
      appName: '北京花粉指数监测',
      docTitle: '北京实时花粉指数监测',
      metaDesc: '北京市16区实时花粉浓度等级监测、24小时逐时趋势与未来分区预报，每小时自动更新。',
      loading: '数据加载中…',
      error: '数据加载失败（{msg}），请稍后刷新重试。',
      langBtn: 'EN',
      heroSub: '全市花粉等级 {n} 级',
      avgConc: '全市平均浓度',
      obsTime: '观测时间',
      updated: '数据更新',
      gridTitle: '16 区实时等级',
      gridHint: '点击任意区，查看其 24 小时趋势',
      trendTitle: '24 小时趋势',
      trendSuffix: '24 小时逐时趋势',
      forecastTitle: '未来分区预报',
      forecastHint: '花粉总量等级预报',
      legendTitle: '等级图例',
      conc: '浓度',
      levelFmt: '{text}（{n} 级）',
      overallFmt: '全市约 {text}（{n} 级）',
      rangeFmt: '{n} 级 · 浓度区间 {range}',
      andAbove: '{min} 以上',
      tipFmt: '{time}｜浓度 {v}｜{text}（{n} 级）',
      latestAdvice: '最新防护建议：',
      noStation: '暂无站点数据',
      noHistory: '该站点暂无 24 小时历史数据',
      noForecast: '暂无预报数据',
      noLegend: '暂无图例数据',
      unknown: '未知',
      ariaChart: '24小时花粉浓度趋势图',
      now: '现在',
      legendObserved: '实测',
      legendEstimated: '预测估计',
      estMark: '（估计）',
      chartDisclaimer: '预测为基于历史规律的统计估计，仅供参考',
      footerSource: '数据来源：<a href="https://pollenwechat.bjpws.com" rel="noopener">北京市花粉监测公共服务平台</a>',
      footerDisclaimer: '本站为个人非营利信息展示项目，数据仅供参考，不构成医疗建议；花粉过敏人群请遵医嘱做好防护。',
      footerUpdate: '由 GitHub Actions 每小时自动更新 · 托管于 GitHub Pages'
    },
    en: {
      appName: 'Beijing Pollen Monitor',
      docTitle: 'Beijing Real-Time Pollen Monitor',
      metaDesc: 'Real-time pollen levels, 24-hour trends and district forecasts for 16 districts of Beijing, updated hourly.',
      loading: 'Loading data…',
      error: 'Failed to load data ({msg}). Please refresh and try again.',
      langBtn: '中文',
      heroSub: 'Citywide pollen level {n}',
      avgConc: 'Citywide avg. concentration',
      obsTime: 'Observed at',
      updated: 'Data updated',
      gridTitle: 'Real-Time Levels by District',
      gridHint: 'Tap a district to see its 24-hour trend',
      trendTitle: '24-Hour Trend',
      trendSuffix: '24-Hour Hourly Trend',
      forecastTitle: 'Forecast by District',
      forecastHint: 'Total pollen level forecast',
      legendTitle: 'Level Legend',
      conc: 'Conc.',
      levelFmt: '{text} · Lv {n}',
      overallFmt: 'Citywide ≈ {text} (Lv {n})',
      rangeFmt: 'Level {n} · Concentration range {range}',
      andAbove: '{min}+',
      tipFmt: '{time} | Conc. {v} | {text} (Lv {n})',
      latestAdvice: 'Latest advice: ',
      noStation: 'No station data available.',
      noHistory: 'No 24-hour history for this station.',
      noForecast: 'No forecast data available.',
      noLegend: 'No legend data available.',
      unknown: 'Unknown',
      ariaChart: '24-hour pollen concentration trend chart',
      now: 'Now',
      legendObserved: 'Observed',
      legendEstimated: 'Estimated',
      estMark: ' (est.)',
      chartDisclaimer: 'Forecast is a statistical estimate based on historical patterns, for reference only.',
      footerSource: 'Data source: <a href="https://pollenwechat.bjpws.com" rel="noopener">Beijing Public Pollen Monitoring Service Platform</a>',
      footerDisclaimer: 'This is a personal, non-profit project. Data is for reference only and does not constitute medical advice. If you suffer from pollen allergies, please follow your doctor\u2019s guidance.',
      footerUpdate: 'Auto-updated hourly by GitHub Actions · Hosted on GitHub Pages'
    }
  };

  // 16 区名拼音映射（API 只返回中文）
  var DISTRICT_EN = {
    '东城区': 'Dongcheng', '西城区': 'Xicheng', '朝阳区': 'Chaoyang', '海淀区': 'Haidian',
    '丰台区': 'Fengtai', '石景山区': 'Shijingshan', '门头沟区': 'Mentougou', '房山区': 'Fangshan',
    '通州区': 'Tongzhou', '顺义区': 'Shunyi', '昌平区': 'Changping', '大兴区': 'Daxing',
    '平谷区': 'Pinggu', '怀柔区': 'Huairou', '密云区': 'Miyun', '延庆区': 'Yanqing'
  };

  // 等级文字：低/较低/中等/高/很高（按等级数字映射，避免依赖 API 文案）
  var LEVEL_EN = {
    '1': 'Low', '2': 'Fairly Low', '3': 'Moderate', '4': 'High', '5': 'Very High'
  };

  // API 的 advice / description 只有中文且文案有多种变体，英文统一回退为各级通用建议
  var LEVEL_ADVICE_EN = {
    '1': 'Pollen concentration is low and barely allergenic. People with pollen allergies can go out freely.',
    '2': 'Pollen concentration is fairly low. Most allergy sufferers can go out as usual; highly sensitive people should take basic precautions.',
    '3': 'Pollen concentration is moderate. Allergy sufferers should avoid parks and areas with dense flowers or trees, and reduce exposure to pollen.',
    '4': 'Pollen concentration is high. Allergy sufferers should minimize time outdoors and wear a mask when going out.',
    '5': 'Pollen concentration is very high. Allergy sufferers should stay indoors as much as possible; severe cases should avoid going out and take effective protective measures.'
  };

  var WEEKDAYS = {
    zh: ['周日', '周一', '周二', '周三', '周四', '周五', '周六'],
    en: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
  };
  var MONTHS_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  var LANG = detectLang();
  var currentData = null;
  var selectedStaId = null;

  function detectLang() {
    try {
      var saved = localStorage.getItem('lang');
      if (saved === 'zh' || saved === 'en') return saved;
    } catch (e) { /* localStorage 不可用时忽略 */ }
    var nav = (navigator.language || 'zh').toLowerCase();
    return nav.indexOf('zh') === 0 ? 'zh' : 'en';
  }

  function t(key) {
    var dict = I18N[LANG] || I18N.zh;
    return dict[key] != null ? dict[key] : (I18N.zh[key] != null ? I18N.zh[key] : key);
  }

  function tf(key, vars) {
    var s = t(key);
    Object.keys(vars || {}).forEach(function (k) {
      s = s.split('{' + k + '}').join(String(vars[k]));
    });
    return s;
  }

  function applyStaticI18n() {
    document.documentElement.lang = LANG === 'zh' ? 'zh-CN' : 'en';
    document.title = t('docTitle');
    var meta = document.querySelector('meta[name="description"]');
    if (meta) meta.setAttribute('content', t('metaDesc'));
    var nodes = document.querySelectorAll('[data-i18n]');
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].innerHTML = t(nodes[i].getAttribute('data-i18n'));
    }
    document.getElementById('lang-toggle').textContent = t('langBtn');
  }

  function setLang(lang) {
    LANG = lang;
    try { localStorage.setItem('lang', lang); } catch (e) { /* 忽略 */ }
    applyStaticI18n();
    if (currentData) render(currentData);
  }

  /* ==================== 工具 ==================== */

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

  function levelName(level, legendMap) {
    if (LANG === 'en' && LEVEL_EN[String(level)]) return LEVEL_EN[String(level)];
    var lg = legendMap[String(level)];
    return (lg && lg.chLevel) || t('unknown');
  }

  function levelColor(level, legendMap) {
    var lg = legendMap[String(level)];
    return (lg && lg.color) || '#e8eaed';
  }

  // 英文模式下统一使用自写的各级建议；中文优先 API 原文
  function levelAdvice(level, legendMap, apiText) {
    if (LANG === 'en') {
      return LEVEL_ADVICE_EN[String(level)] || apiText || '';
    }
    if (apiText) return apiText;
    var lg = legendMap[String(level)];
    return (lg && lg.description) || '';
  }

  function districtName(zhName) {
    return LANG === 'en' ? (DISTRICT_EN[zhName] || zhName) : zhName;
  }

  // "2026-09-10T22:10:48+08:00" -> "2026-09-10 22:10:48"，数据时间均为北京时间，直接展示
  function fmtIso(s) {
    return s ? String(s).replace('T', ' ').replace(/\+.*$/, '') : '-';
  }

  // "2026-09-11" -> zh: "9月11日 周五" / en: "Fri, Sep 11"
  function fmtDate(s) {
    var parts = String(s || '').split('-');
    if (parts.length !== 3) return esc(s);
    var y = +parts[0], m = +parts[1], d = +parts[2];
    if (!y || !m || !d) return esc(s);
    var wd = WEEKDAYS[LANG][new Date(y, m - 1, d).getDay()];
    return LANG === 'en' ? wd + ', ' + MONTHS_EN[m - 1] + ' ' + d : m + '月' + d + '日 ' + wd;
  }

  /* ==================== 启动 ==================== */

  applyStaticI18n();
  document.getElementById('lang-toggle').addEventListener('click', function () {
    setLang(LANG === 'zh' ? 'en' : 'zh');
  });

  // 数据由 fetch.py 生成，字段结构见 data/latest.json
  fetch('data/latest.json?_=' + Date.now())
    .then(function (resp) {
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      return resp.json();
    })
    .then(function (data) {
      document.getElementById('loading').classList.add('hidden');
      document.getElementById('content').classList.remove('hidden');
      currentData = data;
      render(data);
    })
    .catch(function (err) {
      document.getElementById('loading').classList.add('hidden');
      var el = document.getElementById('error');
      el.textContent = tf('error', { msg: err.message });
      el.classList.remove('hidden');
    });

  function render(data) {
    var legendMap = buildLegendMap(data);
    renderOverview(data, legendMap);
    renderGrid(data, legendMap);
    renderForecast(data, legendMap);
    renderLegend(data, legendMap);
  }

  /* ---------- 全市概况 ---------- */
  function renderOverview(data, legendMap) {
    var cw = data.citywide || {};
    document.getElementById('overview').innerHTML =
      '<div class="overview-badge" style="background:' + esc(levelColor(cw.level, legendMap)) + '">' +
        '<div class="overview-level">' + esc(levelName(cw.level, legendMap)) + '</div>' +
        '<div class="overview-sub">' + esc(tf('heroSub', { n: cw.level == null ? '-' : cw.level })) + '</div>' +
      '</div>' +
      '<div class="overview-meta">' +
        '<span>' + esc(t('avgConc')) + ' <b>' + esc(cw.avgValue == null ? '-' : cw.avgValue) + '</b></span>' +
        '<span>' + esc(t('obsTime')) + ' <b>' + esc(cw.obsTime || '-') + '</b></span>' +
        '<span>' + esc(t('updated')) + ' <b>' + esc(fmtIso(data.updatedAt)) + '</b></span>' +
      '</div>' +
      '<p class="advice">' + esc(levelAdvice(cw.level, legendMap, cw.advice)) + '</p>';
  }

  /* ---------- 16区网格 + 趋势图联动 ---------- */
  function renderGrid(data, legendMap) {
    var stations = data.stations || [];
    var valid = stations.some(function (st) { return st.staId === selectedStaId; });
    if (!valid) {
      // 默认选中当前等级最高的站点
      var def = stations.reduce(function (a, b) {
        return (b.level || 0) > ((a && a.level) || 0) ? b : a;
      }, null);
      selectedStaId = def ? def.staId : null;
    }

    var grid = document.getElementById('district-grid');
    grid.innerHTML = '';
    stations.forEach(function (st) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'district';
      btn.dataset.staId = st.staId;
      btn.innerHTML =
        '<span class="d-name">' + esc(districtName(st.staName)) + '</span>' +
        '<span class="d-level" style="background:' + esc(levelColor(st.level, legendMap)) + '">' +
          esc(tf('levelFmt', { text: levelName(st.level, legendMap), n: st.level == null ? '-' : st.level })) + '</span>' +
        '<span class="d-value">' + esc(t('conc')) + ' ' + esc(st.value == null ? '-' : st.value) +
          ' · ' + esc((st.time || '').slice(11, 16)) + '</span>';
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

  /* ---------- 24 小时实测 + 12 小时预测趋势：纯 SVG ---------- */
  function renderChart() {
    var chartEl = document.getElementById('chart');
    var adviceEl = document.getElementById('chart-advice');
    var legendMap = buildLegendMap(currentData);
    var station = (currentData.stations || []).filter(function (st) {
      return st.staId === selectedStaId;
    })[0];
    if (!station) { chartEl.innerHTML = '<p class="notice">' + esc(t('noStation')) + '</p>'; return; }

    document.getElementById('chart-title').textContent =
      districtName(station.staName) + ' · ' + t('trendSuffix');
    var rows = ((currentData.histories || {})[station.staId] || []).filter(function (r) {
      return typeof r.value === 'number' && r.time;
    });
    if (!rows.length) {
      chartEl.innerHTML = '<p class="notice">' + esc(t('noHistory')) + '</p>';
      adviceEl.textContent = '';
      return;
    }
    // 未来 12 小时统计预测；旧数据无 predictions 字段时只画实测
    var preds = ((currentData.predictions || {})[station.staId] || []).filter(function (r) {
      return typeof r.value === 'number' && r.time;
    });

    var last = rows[rows.length - 1];
    var advice = levelAdvice(last.level, legendMap, last.advice);
    adviceEl.textContent = advice ? (t('latestAdvice') + advice) : '';

    var W = 720, H = 260;
    var padL = 36, padR = 14, padT = 16, padB = 34;
    var iw = W - padL - padR, ih = H - padT - padB;
    var nObs = rows.length, nPred = preds.length;
    var total = nObs + nPred;
    function getV(r) { return r.value; }
    var maxV = Math.max.apply(null, rows.map(getV).concat(preds.map(getV)));
    var yMax = Math.max(5, Math.ceil(maxV * 1.25));

    function x(i) { return padL + (total === 1 ? iw / 2 : iw * i / (total - 1)); }
    function y(v) { return padT + ih * (1 - v / yMax); }

    var s = [];
    s.push('<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(t('ariaChart')) + '">');

    // 预测区域底色与“现在/Now”分隔线
    var divX = 0;
    if (nPred) {
      divX = (x(nObs - 1) + x(nObs)) / 2;
      s.push('<rect x="' + divX.toFixed(1) + '" y="' + padT + '" width="' + (W - padR - divX).toFixed(1) +
        '" height="' + ih + '" fill="#f1f3f4" fill-opacity="0.6"/>');
    }

    // 等级背景色带：每个时点一条竖带按当时等级着色，预测段更淡
    var band = iw / total;
    rows.concat(preds).forEach(function (r, i) {
      var bx = Math.max(padL, Math.min(x(i) - band / 2, W - padR - band));
      s.push('<rect x="' + bx.toFixed(1) + '" y="' + padT + '" width="' + (band + 0.5).toFixed(1) +
        '" height="' + ih + '" fill="' + esc(levelColor(r.level, legendMap)) + '"' +
        (i >= nObs ? ' fill-opacity="0.45"' : '') + '/>');
    });

    // 横向网格线与纵轴刻度（Material 风格：浅灰线 #dadce0，文字 #5f6368）
    var ticks = 4;
    for (var ti = 0; ti <= ticks; ti++) {
      var v = yMax * ti / ticks;
      var gy = y(v);
      s.push('<line x1="' + padL + '" y1="' + gy + '" x2="' + (W - padR) + '" y2="' + gy +
        '" stroke="#dadce0" stroke-width="1"/>');
      s.push('<text x="' + (padL - 6) + '" y="' + (gy + 4) + '" text-anchor="end" font-size="11" fill="#5f6368">' +
        Math.round(v) + '</text>');
    }

    // 实测：实线 + 实心点；预测：虚线（从最后一个实测点连出）+ 半透明点
    var obsPts = rows.map(function (r, i) { return x(i).toFixed(1) + ',' + y(r.value).toFixed(1); });
    s.push('<polyline points="' + obsPts.join(' ') + '" fill="none" stroke="#1a73e8" stroke-width="2" stroke-linejoin="round"/>');
    if (nPred) {
      var predPts = [x(nObs - 1).toFixed(1) + ',' + y(last.value).toFixed(1)]
        .concat(preds.map(function (r, j) { return x(nObs + j).toFixed(1) + ',' + y(r.value).toFixed(1); }));
      s.push('<polyline points="' + predPts.join(' ') + '" fill="none" stroke="#1a73e8" stroke-width="2"' +
        ' stroke-dasharray="5,4" stroke-linejoin="round"/>');
    }
    rows.forEach(function (r, i) {
      var tip = tf('tipFmt', { time: r.time, v: r.value, text: levelName(r.level, legendMap), n: r.level });
      s.push('<circle cx="' + x(i).toFixed(1) + '" cy="' + y(r.value).toFixed(1) + '" r="3.2" fill="#1a73e8">' +
        '<title>' + esc(tip) + '</title></circle>');
    });
    preds.forEach(function (r, j) {
      var tip = tf('tipFmt', { time: r.time, v: r.value, text: levelName(r.level, legendMap), n: r.level }) + t('estMark');
      s.push('<circle cx="' + x(nObs + j).toFixed(1) + '" cy="' + y(r.value).toFixed(1) +
        '" r="2.8" fill="#1a73e8" fill-opacity="0.45"><title>' + esc(tip) + '</title></circle>');
    });

    if (nPred) {
      s.push('<line x1="' + divX.toFixed(1) + '" y1="' + padT + '" x2="' + divX.toFixed(1) + '" y2="' + (padT + ih) +
        '" stroke="#9aa0a6" stroke-width="1" stroke-dasharray="3,3"/>');
      s.push('<text x="' + divX.toFixed(1) + '" y="11" text-anchor="middle" font-size="10" fill="#5f6368">' +
        esc(t('now')) + '</text>');
    }

    // 横轴时间标签（"2026-09-10 21:00:00" -> "21:00"），首尾必标，中间每隔3小时
    rows.concat(preds).forEach(function (r, i) {
      if (i !== 0 && i !== total - 1 && i % 3 !== 0) return;
      s.push('<text x="' + x(i).toFixed(1) + '" y="' + (H - 12) + '" text-anchor="middle" font-size="11" fill="#5f6368">' +
        esc(r.time.slice(11, 16)) + '</text>');
    });

    s.push('</svg>');

    // 小图例 + 预测免责声明
    var html = '<div class="chart-legend">' +
      '<span><i class="sw"></i>' + esc(t('legendObserved')) + '</span>' +
      (nPred ? '<span><i class="sw sw-dashed"></i>' + esc(t('legendEstimated')) + '</span>' : '') +
      '</div>' + s.join('') +
      (nPred ? '<p class="chart-disclaimer">' + esc(t('chartDisclaimer')) + '</p>' : '');
    chartEl.innerHTML = html;
  }

  /* ---------- 分区预报 ---------- */
  function renderForecast(data, legendMap) {
    var box = document.getElementById('forecast');
    var days = data.forecast || [];
    if (!days.length) { box.innerHTML = '<p class="notice">' + esc(t('noForecast')) + '</p>'; return; }

    box.innerHTML = days.map(function (day) {
      var areas = day.areas || [];
      var lvls = areas.map(function (a) { return a.level; }).filter(function (v) {
        return typeof v === 'number';
      });
      var overall = lvls.length
        ? Math.round(lvls.reduce(function (a, b) { return a + b; }, 0) / lvls.length)
        : null;

      var chips = areas.map(function (a) {
        return '<span class="forecast-area" style="background:' + esc(levelColor(a.level, legendMap)) + '">' +
          '<span>' + esc(districtName(a.areaName)) + '</span>' +
          '<span class="fa-level">' + esc(levelName(a.level, legendMap)) + '</span></span>';
      }).join('');

      return '<div class="forecast-day">' +
        '<div class="forecast-head">' +
          '<span class="forecast-date">' + fmtDate(day.date) + '</span>' +
          '<span class="forecast-overall" style="background:' + esc(levelColor(overall, legendMap)) + '">' +
            esc(tf('overallFmt', { text: levelName(overall, legendMap), n: overall == null ? '-' : overall })) + '</span>' +
        '</div>' +
        '<div class="forecast-areas">' + chips + '</div>' +
      '</div>';
    }).join('');
  }

  /* ---------- 等级图例 ---------- */
  function renderLegend(data, legendMap) {
    var box = document.getElementById('legend');
    var legends = (data.legends || []).slice().sort(function (a, b) {
      return (+a.level) - (+b.level);
    });
    if (!legends.length) { box.innerHTML = '<p class="notice">' + esc(t('noLegend')) + '</p>'; return; }

    box.innerHTML = legends.map(function (lg) {
      var range = (typeof lg.maxValue === 'number' && lg.maxValue >= 99999)
        ? tf('andAbove', { min: lg.minValue })
        : lg.minValue + ' – ' + lg.maxValue;
      return '<div class="legend-item">' +
        '<span class="legend-swatch" style="background:' + esc(lg.color) + '">' +
          esc(levelName(lg.level, legendMap)) + '</span>' +
        '<div class="legend-body">' +
          '<div class="legend-range">' + esc(tf('rangeFmt', { n: lg.level, range: range })) + '</div>' +
          '<div class="legend-desc">' + esc(levelAdvice(lg.level, legendMap, lg.description)) + '</div>' +
        '</div>' +
      '</div>';
    }).join('');
  }
})();
