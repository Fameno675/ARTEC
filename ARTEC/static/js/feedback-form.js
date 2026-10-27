/* ARTEC — formulaire de feedback : choix d'opérateur, notes 0–10, progression, contrôles client.
   Amélioration progressive : sans JavaScript, les champs Django natifs (select + number) fonctionnent.
   Noms de champs fournis par le backend : operator, score_<code>, comment, form_ts, website. */
(function () {
  'use strict';
  var form = document.querySelector('[data-feedback-form]');
  if (!form) return;

  var LABELS = ['Très mauvais', 'Très mauvais', 'Mauvais', 'Mauvais', 'Insuffisant', 'Moyen', 'Correct', 'Bien', 'Bien', 'Très bien', 'Excellent'];
  function tone(n) { return n <= 4 ? 'is-low' : (n <= 6 ? 'is-mid' : 'is-high'); }  // mêmes seuils que le backend : 0–4 / 5–6 / 7–10

  var answered = 0, total = 0, operatorChosen = false;
  var progressBar = document.querySelector('[data-progress-bar]');
  var progressTrack = document.querySelector('[data-progress-track]');
  var progressText = document.querySelector('[data-progress-text]');

  function updateProgress() {
    var steps = total + 1;                       // l'opérateur compte pour une étape
    var done = answered + (operatorChosen ? 1 : 0);
    var pct = Math.round((done / steps) * 100);
    if (progressBar) progressBar.style.width = pct + '%';
    if (progressTrack) progressTrack.setAttribute('aria-valuenow', String(pct));
    if (progressText) progressText.textContent = (operatorChosen ? 'Opérateur choisi · ' : 'Choisissez un opérateur · ') +
      answered + ' critère' + (answered > 1 ? 's' : '') + ' noté' + (answered > 1 ? 's' : '') + ' sur ' + total;
  }

  /* --- Opérateur : cartes sélectionnables liées au <select> --- */
  var select = form.querySelector('select[name="operator"]');
  if (select) {
    var holder = document.createElement('div');
    holder.className = 'ar-op-choice'; holder.setAttribute('role', 'radiogroup'); holder.setAttribute('aria-label', 'Opérateur évalué');
    Array.prototype.forEach.call(select.options, function (opt, i) {
      if (!opt.value) return;
      var label = document.createElement('label'); label.className = 'ar-op-option';
      var radio = document.createElement('input'); radio.type = 'radio'; radio.name = 'operator_choice'; radio.value = opt.value;
      var card = document.createElement('span'); card.className = 'ar-op-card';
      var mono = document.createElement('span'); mono.className = 'ar-monogram s' + ((i - 1) % 4); mono.setAttribute('aria-hidden', 'true');
      mono.textContent = opt.textContent.trim().slice(0, 2).toUpperCase();
      var name = document.createElement('span'); name.className = 'fw-semibold'; name.textContent = opt.textContent.trim();
      card.append(mono, name); label.append(radio, card); holder.append(label);
      radio.addEventListener('change', function () { select.value = radio.value; operatorChosen = true; updateProgress(); clearErrors(); });
    });
    select.parentNode.insertBefore(holder, select);
    select.classList.add('visually-hidden'); select.setAttribute('tabindex', '-1'); select.setAttribute('aria-hidden', 'true');
    var wanted = select.value || new URLSearchParams(location.search).get('operator');   // ?operator=orange : confort uniquement
    var pre = wanted && holder.querySelector('input[value="' + CSS.escape(wanted) + '"]');
    if (pre) { pre.checked = true; select.value = pre.value; operatorChosen = true; }
  }

  /* --- Notes : groupe de boutons radio 0–10 --- */
  form.querySelectorAll('[data-score-field]').forEach(function (box) {
    var input = box.querySelector('input[name^="score_"]');
    if (!input) return;
    total++;
    var titleId = 'sc-title-' + input.name;
    var title = box.querySelector('[data-score-title]'); if (title) title.id = titleId;
    var group = document.createElement('div'); group.className = 'ar-score-buttons'; group.setAttribute('role', 'radiogroup'); group.setAttribute('aria-labelledby', titleId);
    var readout = document.createElement('div'); readout.className = 'ar-score-readout'; readout.setAttribute('aria-live', 'polite');
    var buttons = [];
    for (var n = 0; n <= 10; n++) {
      var b = document.createElement('button'); b.type = 'button'; b.className = 'ar-score-btn ' + tone(n);
      b.setAttribute('role', 'radio'); b.setAttribute('aria-checked', 'false'); b.setAttribute('tabindex', '-1');
      b.setAttribute('aria-label', n + ' sur 10, ' + LABELS[n]); b.dataset.value = String(n); b.textContent = String(n);
      group.append(b); buttons.push(b);
    }
    var scale = document.createElement('div'); scale.className = 'ar-score-scale';
    scale.innerHTML = '<span>0 · Très mauvais</span><span>10 · Excellent</span>';
    var clear = document.createElement('button'); clear.type = 'button'; clear.className = 'btn btn-link ar-score-clear p-0'; clear.textContent = 'Je ne peux pas évaluer ce critère'; clear.hidden = true;

    function set(value, focus) {
      var was = input.value !== '';
      input.value = value === null ? '' : String(value);
      buttons.forEach(function (x) { var on = value !== null && Number(x.dataset.value) === value; x.setAttribute('aria-checked', String(on)); x.tabIndex = on ? 0 : -1; });
      if (value === null) buttons[0].tabIndex = 0;
      readout.textContent = value === null ? '' : value + ' / 10 · ' + LABELS[value];
      box.classList.toggle('is-answered', value !== null); clear.hidden = value === null;
      if (value !== null && !was) answered++; else if (value === null && was) answered--;
      if (focus && value !== null) buttons[value].focus();
      updateProgress(); clearErrors();
    }
    group.addEventListener('click', function (e) { var t = e.target.closest('.ar-score-btn'); if (t) set(Number(t.dataset.value), false); });
    group.addEventListener('keydown', function (e) {
      var cur = input.value === '' ? null : Number(input.value), next = null;
      if (e.key === 'ArrowRight' || e.key === 'ArrowUp') next = cur === null ? 0 : Math.min(10, cur + 1);
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') next = cur === null ? 0 : Math.max(0, cur - 1);
      else if (e.key === 'Home') next = 0; else if (e.key === 'End') next = 10;
      else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); set(null, false); return; }
      if (next !== null) { e.preventDefault(); set(next, true); }
    });
    clear.addEventListener('click', function () { set(null, false); buttons[0].focus(); });

    var initial = input.value !== '' && /^\d+$/.test(input.value) ? Number(input.value) : null;
    input.type = 'hidden'; input.removeAttribute('min'); input.removeAttribute('max'); input.removeAttribute('placeholder'); input.className = '';
    box.querySelector('[data-score-control]').append(group, scale, readout, clear);
    if (initial !== null && initial <= 10) { input.value = ''; set(initial, false); } else { input.value = ''; buttons[0].tabIndex = 0; }
  });

  /* --- Compteur du commentaire --- */
  var comment = form.querySelector('textarea[name="comment"]'), counter = form.querySelector('[data-comment-count]');
  if (comment && counter) {
    var upd = function () { var n = comment.value.length; counter.textContent = n + ' / 500'; counter.classList.toggle('text-danger', n > 500); };
    comment.addEventListener('input', upd); upd();
  }

  /* --- Contrôles client avant envoi (le serveur revalide tout) --- */
  var errBox = document.getElementById('ar-client-errors');
  function clearErrors() { if (errBox) { errBox.hidden = true; errBox.querySelector('ul').innerHTML = ''; } }
  form.addEventListener('submit', function (e) {
    var problems = [], first = null;
    if (select && !select.value) { problems.push('Choisissez l’opérateur que vous évaluez.'); first = first || form.querySelector('.ar-op-choice input'); }
    if (total > 0 && answered === 0) { problems.push('Notez au moins un critère de 0 à 10.'); first = first || form.querySelector('.ar-score-btn'); }
    if (comment && comment.value.length > 500) { problems.push('Le commentaire dépasse 500 caractères.'); first = first || comment; }
    if (!problems.length) return;
    e.preventDefault(); e.stopImmediatePropagation();
    if (errBox) {
      var ul = errBox.querySelector('ul'); ul.innerHTML = '';
      problems.forEach(function (p) { var li = document.createElement('li'); li.textContent = p; ul.append(li); });
      errBox.hidden = false; errBox.focus();
    }
    if (first) first.focus();
  }, true);

  updateProgress();
})();
