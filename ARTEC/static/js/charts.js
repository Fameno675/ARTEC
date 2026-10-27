/* ARTEC — graphiques SVG natifs (sans bibliothèque).
   Les données viennent exclusivement du backend, via <script type="application/json" id="..."> (filtre json_script).
   Chaque graphique est accompagné, dans la page, d'un tableau HTML équivalent (alternative accessible).
   Types : criteria-bars | sentiment-stack | time-line | bars | stacked-bar                              */
(function () {
  'use strict';
  var NS = 'http://www.w3.org/2000/svg';
  var fr = 'fr-FR';

  function el(name, attrs, kids) {
    var n = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    (kids || []).forEach(function (k) { n.appendChild(typeof k === 'string' ? document.createTextNode(k) : k); });
    return n;
  }
  function text(x, y, s, cls, anchor) { var t = el('text', { x: x, y: y, class: cls || '', 'text-anchor': anchor || 'start' }); t.textContent = s; return t; }
  function fmt(n, d) { return Number(n).toLocaleString(fr, { maximumFractionDigits: d === undefined ? 1 : d }); }
  function readJSON(id) {
    var s = id && document.getElementById(id);
    if (!s) return null;
    try { return JSON.parse(s.textContent); } catch (e) { return null; }
  }
  function cut(s, n) { return s.length > n ? s.slice(0, n - 1) + '…' : s; }
  function empty(root, msg) { root.textContent = ''; var d = document.createElement('div'); d.className = 'ar-chart-empty'; d.textContent = msg; root.appendChild(d); }
  function svgRoot(w, h, label) {
    return el('svg', { viewBox: '0 0 ' + w + ' ' + h, role: 'img', 'aria-label': label, preserveAspectRatio: 'xMinYMin meet' });
  }
  function hatch(svg) {
    svg.appendChild(el('defs', {}, [el('pattern', { id: 'ar-hatch', width: 6, height: 6, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' },
      [el('rect', { width: 6, height: 6, fill: '#fff' }), el('rect', { width: 3, height: 6, fill: '#5b6b80' })])]));
  }
  function legend(root, items) {
    var ul = document.createElement('ul'); ul.className = 'ar-legend'; ul.setAttribute('aria-hidden', 'true');
    items.forEach(function (it) {
      var li = document.createElement('li'); var sw = document.createElement('span'); sw.className = 'ar-swatch ' + it.cls; li.appendChild(sw);
      li.appendChild(document.createTextNode(it.label)); ul.appendChild(li);
    });
    root.appendChild(ul);
  }

  function ctx(root) {
    return {
      criteria: readJSON(root.dataset.criteriaSrc || 'criteria-map') || {},
      operators: readJSON(root.dataset.operatorsSrc || 'operators-map') || {},
      width: Math.max(root.clientWidth || 0, 320) || 640
    };
  }
  function opName(c, ind) { return ind.operator_name || (c.operators[ind.operator] && c.operators[ind.operator].name) || ind.operator || 'Tous'; }
  function opCls(c, ind, i) { var o = c.operators[ind.operator]; return 's' + ((o ? o.index : i) % 4); }
  function critLabel(c, code) { return (c.criteria[code] && c.criteria[code].label) || code; }

  /* ---- Moyenne par critère (barres horizontales groupées par opérateur, IC 95 % si un seul opérateur) ---- */
  function criteriaBars(root, data, c) {
    var inds = (Array.isArray(data) ? data : [data]).filter(function (i) { return i && i.criteria && i.criteria.length; });
    if (!inds.length) return empty(root, 'Aucune note sur cette période.');
    var codes = Object.keys(c.criteria).length ? Object.keys(c.criteria) : [];
    inds.forEach(function (i) { i.criteria.forEach(function (k) { if (codes.indexOf(k.code) === -1) codes.push(k.code); }); });
    codes = codes.filter(function (code) { return inds.some(function (i) { return i.criteria.some(function (k) { return k.code === code; }); }); });
    var W = c.width, padL = 8, padR = 56, barH = 14, gap = 3, rowGap = 26, top = 6, axisH = 26;
    var rowH = 18 + inds.length * (barH + gap) + rowGap - 18;
    var H = top + codes.length * rowH + axisH;
    var svg = svgRoot(W, H, 'Note moyenne sur 10 par critère'); hatch(svg);
    var x0 = padL, x1 = W - padR, sx = function (v) { return x0 + (x1 - x0) * v / 10; };
    for (var g = 0; g <= 10; g += 2) {
      svg.appendChild(el('line', { x1: sx(g), x2: sx(g), y1: top, y2: H - axisH, class: 'ar-grid-line' }));
      svg.appendChild(text(sx(g), H - axisH + 16, String(g), 'ar-muted-text', 'middle'));
    }
    codes.forEach(function (code, r) {
      var y = top + r * rowH;
      var lab = text(x0, y + 12, cut(critLabel(c, code), Math.floor(W / 7)), ''); lab.setAttribute('font-weight', '600'); svg.appendChild(lab);
      inds.forEach(function (ind, i) {
        var k = ind.criteria.filter(function (z) { return z.code === code; })[0]; if (!k || k.mean === null) return;
        var by = y + 18 + i * (barH + gap), cls = opCls(c, ind, i);
        var bar = el('rect', { x: x0, y: by, width: Math.max(1, sx(k.mean) - x0), height: barH, rx: 3, class: cls });
        if (!k.sample_sufficient) { bar.setAttribute('fill-opacity', '.35'); }
        var tip = opName(c, ind) + ' — ' + critLabel(c, code) + ' : ' + fmt(k.mean, 2) + '/10 (n = ' + k.n_ratings + ')' + (k.sample_sufficient ? '' : ' — échantillon insuffisant');
        bar.appendChild(el('title', {}, [tip])); svg.appendChild(bar);
        if (!k.sample_sufficient) svg.appendChild(el('rect', { x: x0, y: by, width: Math.max(1, sx(k.mean) - x0), height: barH, rx: 3, fill: 'url(#ar-hatch)', 'fill-opacity': '.45' }));
        if (inds.length === 1 && k.ci95) {
          var cy = by + barH / 2;
          svg.appendChild(el('path', { class: 'whisker', d: 'M' + sx(k.ci95[0]) + ' ' + cy + 'H' + sx(k.ci95[1]) + 'M' + sx(k.ci95[0]) + ' ' + (cy - 4) + 'v8M' + sx(k.ci95[1]) + ' ' + (cy - 4) + 'v8' }));
        }
        svg.appendChild(text(Math.max(sx(k.mean), k.ci95 && inds.length === 1 ? sx(k.ci95[1]) : 0) + 6, by + barH - 2, fmt(k.mean, 1), ''));
      });
    });
    root.textContent = ''; root.appendChild(svg);
    var items = inds.map(function (ind, i) { return { cls: opCls(c, ind, i), label: opName(c, ind) }; });
    items.push({ cls: 'hatch', label: 'Échantillon insuffisant (non classé)' });
    legend(root, items);
  }

  /* ---- Répartition négatif / neutre / positif par critère (barres empilées 100 %) ---- */
  function sentimentStack(root, data, c) {
    var ind = Array.isArray(data) ? data[+root.dataset.index || 0] : data;
    if (!ind || !ind.criteria || !ind.criteria.length) return empty(root, 'Aucune note sur cette période.');
    var W = c.width, padR = 8, barH = 16, rowH = 42, top = 4;
    var H = top + ind.criteria.length * rowH + 4;
    var svg = svgRoot(W, H, 'Répartition des notes négatives, neutres et positives par critère');
    ind.criteria.forEach(function (k, r) {
      var y = top + r * rowH, x = 0, full = W - padR;
      var lab = text(0, y + 12, cut(critLabel(c, k.code), Math.floor(W / 7)) + '  (n = ' + k.n_ratings + ')', ''); lab.setAttribute('font-weight', '600'); svg.appendChild(lab);
      [['neg', k.negative_rate, 'négatives (0–4)'], ['neu', k.neutral_rate, 'neutres (5–6)'], ['pos', k.positive_rate, 'positives (7–10)']].forEach(function (p) {
        var w = full * p[1]; if (w <= 0) return;
        var rect = el('rect', { x: x, y: y + 18, width: w, height: barH, class: p[0] });
        rect.appendChild(el('title', {}, [critLabel(c, k.code) + ' : ' + fmt(p[1] * 100, 0) + ' % de notes ' + p[2]]));
        svg.appendChild(rect);
        if (w > 34) { var t = text(x + w / 2, y + 18 + barH - 4, fmt(p[1] * 100, 0) + ' %', '', 'middle'); t.setAttribute('style', 'fill:#fff;font-weight:700'); svg.appendChild(t); }
        x += w;
      });
    });
    root.textContent = ''; root.appendChild(svg);
    legend(root, [{ cls: 'neg', label: 'Négatif (0–4)' }, { cls: 'neu', label: 'Neutre (5–6)' }, { cls: 'pos', label: 'Positif (7–10)' }]);
  }

  /* ---- Évolution temporelle de la note moyenne ---- */
  function periodLabel(p, gran) {
    var d = new Date(p + 'T00:00:00');
    if (isNaN(d)) return p;
    return gran === 'month' ? d.toLocaleDateString(fr, { month: 'short', year: '2-digit' }) : d.toLocaleDateString(fr, { day: '2-digit', month: '2-digit' });
  }
  function timeLine(root, data, c) {
    var gran = root.dataset.granularity || 'month';
    var lines = [];
    if (root.dataset.pointsSrc) {
      var pts = readJSON(root.dataset.pointsSrc) || [];
      lines.push({ name: root.dataset.label || 'Note moyenne', cls: 's0', points: pts });
    } else {
      (Array.isArray(data) ? data : [data]).forEach(function (ind, i) { if (ind && ind.series && ind.series.length) lines.push({ name: opName(c, ind), cls: opCls(c, ind, i), points: ind.series }); });
    }
    var periods = [];
    lines.forEach(function (l) { l.points.forEach(function (p) { if (periods.indexOf(p.period) === -1) periods.push(p.period); }); });
    periods.sort();
    if (!periods.length) return empty(root, 'Pas assez de données pour afficher une évolution.');
    var W = c.width, H = Math.max(230, Math.min(320, W * .5)), pl = 34, pr = 14, pt = 12, pb = 30;
    var sx = function (i) { return periods.length === 1 ? (pl + (W - pr)) / 2 : pl + (W - pl - pr) * i / (periods.length - 1); };
    var sy = function (v) { return pt + (H - pt - pb) * (1 - v / 10); };
    var svg = svgRoot(W, H, 'Évolution de la note moyenne sur 10');
    for (var g = 0; g <= 10; g += 2) {
      svg.appendChild(el('line', { x1: pl, x2: W - pr, y1: sy(g), y2: sy(g), class: 'ar-grid-line' }));
      svg.appendChild(text(pl - 8, sy(g) + 4, String(g), 'ar-muted-text', 'end'));
    }
    var every = Math.ceil(periods.length / Math.max(2, Math.floor((W - pl) / 62)));
    periods.forEach(function (p, i) { if (i % every === 0) svg.appendChild(text(sx(i), H - 8, periodLabel(p, gran), 'ar-muted-text', 'middle')); });
    svg.appendChild(el('line', { x1: pl, x2: W - pr, y1: sy(0), y2: sy(0), class: 'ar-axis-line' }));
    lines.forEach(function (l) {
      var d = ''; l.points.slice().sort(function (a, b) { return a.period < b.period ? -1 : 1; }).forEach(function (p, j) {
        var i = periods.indexOf(p.period); d += (j ? 'L' : 'M') + sx(i) + ' ' + sy(p.quality_score);
      });
      svg.appendChild(el('path', { d: d, class: 'line-path ' + l.cls }));
      l.points.forEach(function (p) {
        var i = periods.indexOf(p.period), small = p.sample_sufficient === false;
        var dot = el('circle', { cx: sx(i), cy: sy(p.quality_score), r: 4.5, class: 'dot ' + l.cls + (small ? ' is-small' : '') });
        dot.appendChild(el('title', {}, [l.name + ' · ' + periodLabel(p.period, gran) + ' : ' + fmt(p.quality_score, 2) + '/10 (n = ' + p.n_submissions + ' avis' + (small ? ', échantillon insuffisant' : '') + ')']));
        svg.appendChild(dot);
      });
    });
    root.textContent = ''; root.appendChild(svg);
    legend(root, lines.map(function (l) { return { cls: l.cls, label: l.name }; }).concat([{ cls: 'hatch', label: 'Point creux : échantillon insuffisant' }]));
  }

  /* ---- Barres simples (dictionnaire {clé: valeur} ou liste [{label, value}]) ---- */
  function bars(root, data) {
    var labels = {}; try { labels = JSON.parse(root.dataset.labels || '{}'); } catch (e) { /* ignore */ }
    var rows = Array.isArray(data) ? data : Object.keys(data || {}).map(function (k) { return { label: labels[k] || k, value: data[k] }; });
    rows = rows.filter(function (r) { return typeof r.value === 'number'; });
    var max = Math.max.apply(null, rows.map(function (r) { return r.value; }).concat([0]));
    if (!rows.length || max === 0) return empty(root, root.dataset.emptyText || 'Aucune donnée à afficher.');
    var W = (root.clientWidth || 0) || 640; W = Math.max(W, 300);
    var rowH = 34, labW = Math.min(190, W * .42), top = 2, H = top + rows.length * rowH + 2, cls = root.dataset.series || 's0';
    var svg = svgRoot(W, H, root.dataset.title || 'Graphique en barres');
    rows.forEach(function (r, i) {
      var y = top + i * rowH, w = (W - labW - 52) * r.value / max;
      svg.appendChild(text(0, y + 20, cut(r.label, Math.floor(labW / 7)), ''));
      var rect = el('rect', { x: labW, y: y + 6, width: Math.max(r.value ? 3 : 0, w), height: 18, rx: 3, class: cls });
      rect.appendChild(el('title', {}, [r.label + ' : ' + fmt(r.value, 0)])); svg.appendChild(rect);
      svg.appendChild(text(labW + Math.max(r.value ? 3 : 0, w) + 6, y + 20, fmt(r.value, 0), ''));
    });
    root.textContent = ''; root.appendChild(svg);
  }

  /* ---- Barre empilée unique (ex. résultat des imports) : data-parts='[{"key":"accepted_rows","label":"Acceptées","cls":"pos"}]' ---- */
  function stackedBar(root, data) {
    var parts = []; try { parts = JSON.parse(root.dataset.parts || '[]'); } catch (e) { /* ignore */ }
    var total = parts.reduce(function (s, p) { return s + (data[p.key] || 0); }, 0);
    if (!total) return empty(root, root.dataset.emptyText || 'Aucune ligne importée.');
    var W = Math.max((root.clientWidth || 0) || 640, 300), svg = svgRoot(W, 34, root.dataset.title || 'Répartition'), x = 0;
    parts.forEach(function (p) {
      var v = data[p.key] || 0, w = W * v / total; if (!v) return;
      var rect = el('rect', { x: x, y: 4, width: w, height: 26, class: p.cls }); rect.appendChild(el('title', {}, [p.label + ' : ' + fmt(v, 0) + ' (' + fmt(v / total * 100, 1) + ' %)'])); svg.appendChild(rect); x += w;
    });
    root.textContent = ''; root.appendChild(svg);
    legend(root, parts.map(function (p) { return { cls: p.cls, label: p.label + ' : ' + fmt(data[p.key] || 0, 0) }; }));
  }

  var TYPES = { 'criteria-bars': criteriaBars, 'sentiment-stack': sentimentStack, 'time-line': timeLine, 'bars': bars, 'stacked-bar': stackedBar };

  function render(root) {
    var fn = TYPES[root.dataset.chart]; if (!fn) return;
    var data = readJSON(root.dataset.src);
    var c = ctx(root);
    if (data === null && !root.dataset.pointsSrc) return empty(root, 'Données indisponibles.');
    try { fn(root, data, c); } catch (e) { empty(root, 'Le graphique n’a pas pu être affiché ; consultez le tableau ci-dessous.'); if (window.console) console.error(e); }
  }
  function init() {
    var roots = Array.prototype.slice.call(document.querySelectorAll('[data-chart]'));
    roots.forEach(function (r) { r.dataset.w = String(r.clientWidth || 0); render(r); });
    if ('ResizeObserver' in window) {
      var t; var ro = new ResizeObserver(function (entries) {
        clearTimeout(t); t = setTimeout(function () {
          entries.forEach(function (e) { var w = Math.round(e.contentRect.width); if (Math.abs(w - Number(e.target.dataset.w || 0)) > 8) { e.target.dataset.w = String(w); render(e.target); } });
        }, 150);
      });
      roots.forEach(function (r) { ro.observe(r); });
    }
  }
  window.ArtecCharts = { render: render, init: init };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
