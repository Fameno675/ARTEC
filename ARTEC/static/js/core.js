/* ARTEC — comportements communs : chargement, confirmation, filtre de tableau, hors-ligne.
   Aucune dépendance autre que Bootstrap (modale). Les contrôles côté client améliorent
   l'expérience ; la validation et la sécurité restent côté serveur. */
(function () {
  'use strict';

  var bar = document.querySelector('.ar-loading-bar');

  /* --- Confirmation avant action sensible : <form data-confirm="..."> ou <button data-confirm="..."> --- */
  var modalEl = document.getElementById('ar-confirm-modal');
  var pending = null;
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement) || form.dataset.confirmed === '1') return;
    var sub = e.submitter;
    var message = (sub && sub.dataset.confirm) || form.dataset.confirm;
    if (!message || !modalEl || !window.bootstrap) return;
    e.preventDefault();
    pending = { form: form, submitter: sub || null };
    modalEl.querySelector('[data-confirm-message]').textContent = message;
    window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
  }, true);
  if (modalEl) {
    modalEl.querySelector('[data-confirm-accept]').addEventListener('click', function () {
      if (!pending) return;
      var p = pending; pending = null;
      window.bootstrap.Modal.getInstance(modalEl).hide();
      p.form.dataset.confirmed = '1';
      if (p.form.requestSubmit) p.form.requestSubmit(p.submitter || undefined); else p.form.submit();
    });
    modalEl.addEventListener('hidden.bs.modal', function () { pending = null; });
  }

  /* --- Indicateur de chargement + anti double envoi --- */
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!(form instanceof HTMLFormElement) || e.defaultPrevented || form.hasAttribute('data-no-loading')) return;
    if (bar) bar.classList.add('is-active');
    var buttons = form.querySelectorAll('button[type="submit"], button:not([type])');
    // différé : le navigateur lit d'abord name/value du bouton cliqué
    setTimeout(function () {
      buttons.forEach(function (b) {
        b.disabled = true;
        b.setAttribute('aria-busy', 'true');
        if (!b.querySelector('.spinner-border')) {
          var s = document.createElement('span');
          s.className = 'spinner-border spinner-border-sm me-2';
          s.setAttribute('aria-hidden', 'true');
          b.prepend(s);
        }
        if (b.dataset.loadingText) b.dataset.originalText = b.lastChild.textContent, b.lastChild.textContent = ' ' + b.dataset.loadingText;
      });
    }, 0);
  });
  window.addEventListener('pageshow', function (e) {      // retour arrière (cache de page) : réactiver
    if (!e.persisted) return;
    if (bar) bar.classList.remove('is-active');
    document.querySelectorAll('button[aria-busy="true"]').forEach(function (b) {
      b.disabled = false; b.removeAttribute('aria-busy');
      var s = b.querySelector('.spinner-border'); if (s) s.remove();
      if (b.dataset.originalText) b.lastChild.textContent = b.dataset.originalText;
    });
    document.querySelectorAll('form[data-confirmed]').forEach(function (f) { delete f.dataset.confirmed; });
  });

  /* --- Filtre rapide d'un tableau (page courante uniquement) --- */
  document.querySelectorAll('[data-table-filter]').forEach(function (input) {
    var table = document.querySelector(input.dataset.tableFilter);
    if (!table) return;
    var counter = document.querySelector(input.dataset.filterCount || '');
    input.addEventListener('input', function () {
      var q = input.value.trim().toLocaleLowerCase('fr');
      var rows = table.querySelectorAll('tbody tr'), visible = 0;
      rows.forEach(function (r) {
        var show = !q || r.textContent.toLocaleLowerCase('fr').indexOf(q) !== -1;
        r.hidden = !show; if (show) visible++;
      });
      if (counter) counter.textContent = q ? visible + ' ligne(s) sur ' + rows.length + ' affichée(s)' : '';
    });
  });

  /* --- Hors-ligne --- */
  var offline = document.querySelector('.ar-offline');
  function sync() { if (offline) offline.classList.toggle('is-visible', !navigator.onLine); }
  window.addEventListener('online', sync); window.addEventListener('offline', sync); sync();

  /* --- Focus sur la première erreur serveur --- */
  var firstError = document.querySelector('.ar-field-error, .is-invalid, [aria-invalid="true"]');
  if (firstError && !document.querySelector('[data-feedback-form]')) {
    var target = firstError.closest('.mb-3, .ar-score') || firstError;
    var input = target.querySelector('input, select, textarea');
    if (input) input.focus({ preventScroll: true });
    target.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  }
})();
