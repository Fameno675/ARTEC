/* ARTEC — sélection de fichier d'import : contrôles et aperçu côté client (confort uniquement).
   Le backend revalide : type, taille, colonnes, valeurs, doublons. Aucun contenu n'est exécuté :
   tout est affiché via textContent. */
(function () {
  'use strict';
  document.querySelectorAll('[data-file-upload]').forEach(function (root) {
    var input = root.querySelector('input[type="file"]');
    var zone = root.querySelector('.ar-dropzone');
    var out = root.querySelector('[data-file-preview]');
    var submit = root.closest('form').querySelector('[type="submit"]');
    if (!input || !out) return;
    var maxBytes = Number(root.dataset.maxBytes || 10485760);
    var exts = (root.dataset.extensions || '.csv,.xlsx').split(',');
    var required = (root.dataset.requiredColumns || 'collected_at').split(',');
    var known = JSON.parse((document.getElementById(root.dataset.knownColumns) || { textContent: '[]' }).textContent);

    function fmtSize(n) { return n < 1048576 ? (n / 1024).toFixed(1).replace('.', ',') + ' Ko' : (n / 1048576).toFixed(2).replace('.', ',') + ' Mo'; }
    function note(cls, icon, text) {
      var d = document.createElement('div'); d.className = 'ar-notice is-' + cls; d.setAttribute('role', cls === 'danger' ? 'alert' : 'status');
      var i = document.createElement('i'); i.className = 'bi bi-' + icon; i.setAttribute('aria-hidden', 'true');
      var s = document.createElement('div'); s.textContent = text; d.append(i, s); return d;
    }
    function parseLine(line, sep) {
      var res = [], cur = '', q = false;
      for (var i = 0; i < line.length; i++) {
        var c = line[i];
        if (q) { if (c === '"') { if (line[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += c; }
        else if (c === '"') q = true; else if (c === sep) { res.push(cur); cur = ''; } else cur += c;
      }
      res.push(cur); return res;
    }
    function reset() { out.textContent = ''; if (submit) submit.disabled = false; }

    function inspect(file) {
      reset();
      var ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase();
      var bad = false;
      var dl = document.createElement('dl'); dl.className = 'ar-kv row row-cols-1 row-cols-sm-3 mb-2';
      [['Fichier', file.name], ['Taille', fmtSize(file.size)], ['Format', ext || 'inconnu']].forEach(function (kv) {
        var c = document.createElement('div'); c.className = 'col'; var t = document.createElement('dt'); t.textContent = kv[0]; var d = document.createElement('dd'); d.textContent = kv[1]; c.append(t, d); dl.append(c);
      });
      out.append(dl);
      if (exts.indexOf(ext) === -1) { out.append(note('danger', 'x-circle', 'Format refusé : seuls ' + exts.join(' et ') + ' sont acceptés.')); bad = true; }
      if (file.size > maxBytes) { out.append(note('danger', 'x-circle', 'Fichier trop volumineux (maximum ' + fmtSize(maxBytes) + ').')); bad = true; }
      if (file.size === 0) { out.append(note('danger', 'x-circle', 'Le fichier est vide.')); bad = true; }
      if (bad) { if (submit) submit.disabled = true; return; }
      if (ext === '.xlsx') {
        out.append(note('info', 'info-circle', 'Aperçu non disponible pour Excel : la structure et les valeurs seront vérifiées par le serveur à l’import (feuille « feedback », sinon la première).'));
        return;
      }
      file.slice(0, 65536).text().then(function (text) {
        text = text.replace(/^\uFEFF/, '');
        var lines = text.split(/\r?\n/).filter(function (l) { return l.trim() !== ''; });
        if (!lines.length) { out.append(note('danger', 'x-circle', 'Aucune ligne lisible.')); if (submit) submit.disabled = true; return; }
        var sep = (lines[0].split(';').length > lines[0].split(',').length) ? ';' : ',';
        var header = parseLine(lines[0], sep).map(function (h) { return h.trim().toLowerCase(); });
        var missing = required.filter(function (r) { return header.indexOf(r) === -1; });
        var scoreCols = header.filter(function (h) { return known.indexOf(h) !== -1 && h.indexOf('score_') === 0; });
        var unknown = header.filter(function (h) { return h && known.indexOf(h) === -1; });
        if (missing.length) { out.append(note('danger', 'x-circle', 'Colonnes obligatoires absentes : ' + missing.join(', ') + '.')); }
        if (!scoreCols.length) { out.append(note('danger', 'x-circle', 'Aucune colonne de note reconnue (score_…).')); }
        if (missing.length || !scoreCols.length) { if (submit) submit.disabled = true; }
        else out.append(note('success', 'check-circle', 'Structure plausible : séparateur « ' + sep + ' », ' + scoreCols.length + ' colonne(s) de notes reconnue(s).'));
        if (unknown.length) out.append(note('warning', 'exclamation-triangle', 'Colonnes ignorées par le serveur : ' + unknown.join(', ') + '.'));
        var table = document.createElement('table'); table.className = 'ar-table';
        var cap = document.createElement('caption'); cap.textContent = 'Aperçu des premières lignes (' + Math.min(5, lines.length - 1) + ' sur le début du fichier)'; table.append(cap);
        var thead = document.createElement('thead'), tr = document.createElement('tr');
        header.forEach(function (h) { var th = document.createElement('th'); th.scope = 'col'; th.textContent = h; tr.append(th); }); thead.append(tr); table.append(thead);
        var tb = document.createElement('tbody');
        lines.slice(1, 6).forEach(function (l) { var r = document.createElement('tr'); parseLine(l, sep).forEach(function (c) { var td = document.createElement('td'); td.textContent = c; r.append(td); }); tb.append(r); });
        table.append(tb); var wrap = document.createElement('div'); wrap.className = 'ar-table-wrap'; wrap.append(table); out.append(wrap);
      });
    }

    input.addEventListener('change', function () { if (input.files && input.files[0]) inspect(input.files[0]); else reset(); });
    if (zone) {
      ['dragenter', 'dragover'].forEach(function (ev) { zone.addEventListener(ev, function (e) { e.preventDefault(); zone.classList.add('is-dragover'); }); });
      ['dragleave', 'drop'].forEach(function (ev) { zone.addEventListener(ev, function (e) { e.preventDefault(); zone.classList.remove('is-dragover'); }); });
      zone.addEventListener('drop', function (e) { if (e.dataTransfer && e.dataTransfer.files.length) { input.files = e.dataTransfer.files; input.dispatchEvent(new Event('change')); } });
    }
  });
})();
