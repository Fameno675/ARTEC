/* ARTEC — page « Donner mon avis » : l'opérateur choisi est transmis au formulaire via ?operator=<code>
   (confort uniquement : le serveur ignore ce paramètre ; l'opérateur est toujours choisi et validé dans le formulaire). */
(function () {
  'use strict';
  var radios = document.querySelectorAll('[data-operator-picker] input[type="radio"]');
  var links = document.querySelectorAll('[data-survey-link]');
  if (!radios.length) return;
  function update(code) {
    links.forEach(function (a) {
      var base = a.getAttribute('data-base') || a.getAttribute('href').split('?')[0];
      a.setAttribute('data-base', base);
      a.setAttribute('href', code ? base + '?operator=' + encodeURIComponent(code) : base);
    });
  }
  radios.forEach(function (r) { r.addEventListener('change', function () { update(r.value); }); });
  var pre = new URLSearchParams(location.search).get('operator');
  Array.prototype.forEach.call(radios, function (r) { if (r.value === pre) { r.checked = true; update(pre); } });
})();
