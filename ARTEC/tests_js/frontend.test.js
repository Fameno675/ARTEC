/* Tests du JavaScript natif d'ARTEC dans jsdom, sur les vraies pages rendues par Django.
   Prérequis (outil de test uniquement, rien à déployer) : npm install jsdom ; PYTHONPATH=. python tests_js/dump_pages.py
   Exécution : node tests_js/frontend.test.js                                                            */
const fs = require('fs'), path = require('path');
const { JSDOM } = require('jsdom');
const STATIC = path.join(__dirname, '..', 'static');
const PAGES = process.env.PAGES_DIR || '/tmp/pages';
let passed = 0, failed = 0; const failures = [];
function ok(cond, msg) { if (cond) passed++; else { failed++; failures.push(msg); } }
function eq(a, b, msg) { ok(JSON.stringify(a) === JSON.stringify(b), `${msg} — obtenu ${JSON.stringify(a)}, attendu ${JSON.stringify(b)}`); }

async function load(page, scripts, url) {
  const html = typeof page === 'string' && page.includes('<') ? page : fs.readFileSync(path.join(PAGES, page + '.html'), 'utf8');
  const dom = new JSDOM(html, { runScripts: 'outside-only', pretendToBeVisual: true, url: url || 'http://localhost/' });
  const w = dom.window;
  if (w.document.readyState === 'loading') await new Promise(r => w.document.addEventListener('DOMContentLoaded', r));
  w.CSS = w.CSS || { escape: s => String(s).replace(/[^a-zA-Z0-9_-]/g, '\\$&') };
  w.matchMedia = w.matchMedia || (() => ({ matches: false }));
  w.Element.prototype.scrollIntoView = function () {};
  w.Blob.prototype.text = w.Blob.prototype.text || function () { return new Promise(res => { const r = new w.FileReader(); r.onload = () => res(r.result); r.readAsText(this); }); };
  scripts.forEach(s => w.eval(fs.readFileSync(path.join(STATIC, 'js', s), 'utf8')));
  return w;
}
const q = (w, s) => w.document.querySelector(s), qa = (w, s) => Array.from(w.document.querySelectorAll(s));
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
const submit = (w, form, submitter) => { const ev = new w.SubmitEvent('submit', { bubbles: true, cancelable: true, submitter }); form.dispatchEvent(ev); return ev; };
const tick = (ms = 0) => new Promise(r => setTimeout(r, ms));

(async function main() {
  /* ---------- Formulaire de feedback ---------- */
  {
    const w = await load('survey_detail', ['core.js', 'feedback-form.js']);
    const form = q(w, '[data-feedback-form]');
    eq(qa(w, '.ar-op-option').length, 3, 'feedback: 3 cartes opérateur (orange, yas, airtel)');
    eq(qa(w, '[data-score-field]').length, 10, 'feedback: 10 critères');
    eq(qa(w, '.ar-score-buttons').map(g => g.children.length), Array(10).fill(11), 'feedback: 11 boutons (0 à 10) par critère');
    eq(q(w, 'input[name="score_customer_service"]').type, 'hidden', 'feedback: champ number natif devenu hidden (valeur conservée pour le serveur)');
    eq(q(w, 'select[name="operator"]').classList.contains('visually-hidden'), true, 'feedback: select natif conservé mais masqué');
    ok(q(w, '[data-progress-text]').textContent.includes('0 critère noté sur 10'), 'feedback: progression initiale');

    let ev = submit(w, form, q(w, 'button[type=submit]'));
    eq(ev.defaultPrevented, true, 'feedback: envoi vide bloqué côté client');
    eq(q(w, '#ar-client-errors').hidden, false, 'feedback: erreurs affichées');
    eq(qa(w, '#ar-client-errors li').length, 2, 'feedback: 2 messages (opérateur + au moins un critère)');

    click(w, q(w, '.ar-op-option input[value="yas"]'));
    eq(q(w, 'select[name="operator"]').value, 'yas', 'feedback: carte opérateur -> select synchronisé');
    const grp = qa(w, '.ar-score-buttons')[0];
    click(w, grp.children[7]);
    eq(q(w, 'input[name="score_mobile_data_speed"]').value, '7', 'feedback: clic sur 7 -> valeur 7');
    eq(grp.children[7].getAttribute('aria-checked'), 'true', 'feedback: aria-checked');
    ok(grp.parentElement.querySelector('.ar-score-readout').textContent.includes('7 / 10 · Bien'), 'feedback: libellé de la note');
    ok(q(w, '[data-progress-text]').textContent.includes('Opérateur choisi · 1 critère noté sur 10'), 'feedback: progression mise à jour');
    eq(q(w, '[data-progress-track]').getAttribute('aria-valuenow'), '18', 'feedback: aria-valuenow = 2/11 étapes');

    grp.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    eq(q(w, 'input[name="score_mobile_data_speed"]').value, '8', 'feedback: flèche droite -> 8');
    grp.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Home', bubbles: true }));
    eq(q(w, 'input[name="score_mobile_data_speed"]').value, '0', 'feedback: Home -> 0 (0 est une note valide)');
    grp.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'End', bubbles: true }));
    eq(q(w, 'input[name="score_mobile_data_speed"]').value, '10', 'feedback: End -> 10');
    grp.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    eq(q(w, 'input[name="score_mobile_data_speed"]').value, '10', 'feedback: borné à 10');
    grp.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Delete', bubbles: true }));
    eq(q(w, 'input[name="score_mobile_data_speed"]').value, '', 'feedback: Suppr -> non évalué (champ vide)');
    click(w, grp.children[3]);
    eq(grp.children[3].classList.contains('is-low'), true, 'feedback: 3 = classe "faible" (0–4, cohérent avec le backend)');
    eq(grp.children[6].classList.contains('is-mid'), true, 'feedback: 6 = classe "moyen" (5–6)');
    eq(grp.children[7].classList.contains('is-high'), true, 'feedback: 7 = classe "bon" (7–10)');

    ev = submit(w, form, q(w, 'button[type=submit]'));
    eq(ev.defaultPrevented, false, 'feedback: envoi valide autorisé');
    await tick(5);
    ok(q(w, 'button[type=submit]').disabled, 'feedback: bouton désactivé après envoi (anti double clic)');
    ok(q(w, 'button[type=submit] .spinner-border'), 'feedback: indicateur de chargement affiché');

    const c = q(w, 'textarea[name="comment"]'); c.value = 'x'.repeat(501); c.dispatchEvent(new w.Event('input'));
    ok(q(w, '[data-comment-count]').textContent.startsWith('501'), 'feedback: compteur de commentaire');
    const hp = q(w, 'input[name="website"]');
    ok(hp.closest('.hp-field'), 'feedback: champ piège (honeypot) conservé et masqué'); eq(hp.value, '', 'feedback: honeypot vide');
    ok(q(w, 'input[name="form_ts"]').value.length > 10, 'feedback: jeton horodaté fourni par le serveur conservé');
  }
  {
    const w = await load('survey_detail', ['core.js', 'feedback-form.js'], 'http://localhost/sondages/x/?operator=airtel');
    eq(q(w, 'select[name="operator"]').value, 'airtel', 'feedback: ?operator=airtel présélectionne');
    ok(q(w, '.ar-op-option input[value="airtel"]').checked, 'feedback: carte présélectionnée');
    ok(q(w, '[data-progress-text]').textContent.startsWith('Opérateur choisi'), 'feedback: progression tient compte de la présélection');
  }
  {
    const w = await load('survey_list', ['survey-list.js'], 'http://localhost/sondages/');
    const link = q(w, '[data-survey-link]'); const base = link.getAttribute('href');
    click(w, q(w, '[data-operator-picker] input[value="yas"]'));
    eq(link.getAttribute('href'), base + '?operator=yas', 'liste sondages: opérateur choisi propagé au lien');
  }

  /* ---------- Graphiques ---------- */
  {
    const w = await load('results', ['charts.js']);
    const data = JSON.parse(q(w, '#indicators-data').textContent);
    const bars = q(w, '[data-chart="criteria-bars"] svg');
    ok(bars, 'graphique: barres par critère rendues');
    const expectedBars = data.reduce((s, i) => s + i.criteria.length, 0);
    eq(qa(w, '[data-chart="criteria-bars"] rect.s0, [data-chart="criteria-bars"] rect.s1, [data-chart="criteria-bars"] rect.s2').filter(r => !r.getAttribute('fill')).length, expectedBars, 'graphique: une barre par (opérateur × critère) avec données');
    const airtel = data.find(i => i.operator === 'airtel');
    eq(airtel.sample_sufficient, false, 'données: Airtel sous le seuil');
    const hatched = qa(w, '[data-chart="criteria-bars"] rect[fill="url(#ar-hatch)"]').length;
    eq(hatched, airtel.criteria.filter(c => !c.sample_sufficient).length, 'graphique: hachures sur les barres à petit échantillon');
    ok(qa(w, '[data-chart="criteria-bars"] .ar-legend li').length === 4, 'graphique: légende = 3 opérateurs + échantillon insuffisant');
    ok(qa(w, '[data-chart="criteria-bars"] title').every(t => /\d/.test(t.textContent)), 'graphique: infobulles chiffrées');
    const line = q(w, '[data-chart="time-line"] svg');
    ok(line, 'graphique: courbes rendues');
    eq(qa(w, '[data-chart="time-line"] path.line-path').length, data.filter(i => i.series.length).length, 'graphique: une courbe par opérateur');
    eq(qa(w, '[data-chart="time-line"] circle').length, data.reduce((s, i) => s + i.series.length, 0), 'graphique: un point par période et opérateur');
    ok(qa(w, '[data-chart="time-line"] circle.is-small').length > 0, 'graphique: points creux pour les petits échantillons');
    ok(q(w, '[data-chart="criteria-bars"] svg').getAttribute('aria-label').includes('Note moyenne'), 'graphique: alternative textuelle (aria-label)');
    ok(q(w, '[data-chart="criteria-bars"] text').textContent.length > 0, 'graphique: libellés lisibles (pas de code brut)');
    ok(!qa(w, '[data-chart="criteria-bars"] text').some(t => /^[a-z]+_[a-z_]+$/.test(t.textContent)), 'graphique: aucun code technique affiché comme libellé');
  }
  {
    const w = await load('op_dashboard', ['charts.js']);
    const ind = JSON.parse(q(w, '#indicators-data').textContent);
    eq(qa(w, '[data-chart="criteria-bars"] path.whisker').length, ind.criteria.length, 'opérateur: IC 95 % affiché pour chaque critère');
    eq(qa(w, '[data-chart="sentiment-stack"] rect.neg').length > 0 && qa(w, '[data-chart="sentiment-stack"] rect.pos').length > 0, true, 'opérateur: répartition négatif/positif');
    const series = JSON.parse(q(w, '#series-data').textContent);
    eq(qa(w, '[data-chart="time-line"] circle').length, series.length, 'opérateur: points de la série unique');
    ok(q(w, '[data-chart="bars"] svg'), 'opérateur: réclamations par statut');
  }
  {
    const w = await load('artec_dashboard', ['charts.js']);
    const src = JSON.parse(q(w, '#sources-data').textContent);
    eq(qa(w, '[data-chart="bars"][data-src="sources-data"] rect').length, Object.keys(src).length, 'ARTEC: une barre par source');
    ok(qa(w, '[data-chart="bars"][data-src="sources-data"] text').some(t => t.textContent === 'Source externe'), 'ARTEC: libellé français des sources');
    ok(q(w, '[data-chart="stacked-bar"] .ar-chart-empty'), 'ARTEC: aucun import -> état vide explicite (pas de graphique vide)');
    eq(qa(w, '[data-chart="time-line"] path.line-path').length, 3, 'ARTEC: évolution des 3 opérateurs');
  }
  {
    const w = await load('results', ['charts.js']);   // robustesse : données vides, malveillantes, absentes
    const root = q(w, '[data-chart="criteria-bars"]');
    q(w, '#indicators-data').textContent = '[]';
    w.ArtecCharts.render(root);
    ok(root.querySelector('.ar-chart-empty'), 'graphique: données vides -> message');
    q(w, '#indicators-data').textContent = JSON.stringify([{ operator: 'orange', operator_name: '<img src=x onerror=alert(1)>', criteria: [{ code: 'customer_service', mean: 7, n_ratings: 40, ci95: [6, 8], sample_sufficient: true }], series: [] }]);
    w.ArtecCharts.render(root);
    eq(root.querySelectorAll('img').length, 0, 'sécurité: nom d’opérateur malveillant non interprété comme HTML (graphique)');
    ok(root.textContent.includes('<img src=x'), 'sécurité: affiché comme texte brut');
    q(w, '#indicators-data').textContent = '{pas du json';
    w.ArtecCharts.render(root);
    ok(root.querySelector('.ar-chart-empty'), 'graphique: JSON invalide -> message, pas de plantage');
    const ghost = w.document.createElement('div'); ghost.dataset.chart = 'criteria-bars'; ghost.dataset.src = 'absent'; w.document.body.append(ghost);
    w.ArtecCharts.render(ghost); ok(ghost.querySelector('.ar-chart-empty'), 'graphique: source absente -> message');
  }

  /* ---------- Aperçu de fichier avant import ---------- */
  async function preview(name, content, opts = {}) {
    const w = await load('artec_import_create', ['core.js', 'file-upload.js']);
    const input = q(w, 'input[type=file]');
    const file = new w.File([content], name, { type: 'text/plain' });
    if (opts.size) Object.defineProperty(file, 'size', { value: opts.size });
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    input.dispatchEvent(new w.Event('change', { bubbles: true }));
    await tick(30);
    return { w, out: q(w, '[data-file-preview]'), submit: q(w, 'main form button[type=submit]') };
  }
  const HEAD = 'external_id,operator_code,collected_at,score_mobile_data_speed,score_customer_service,comment\n';
  {
    const r = await preview('ok.csv', HEAD + 'A1,orange,2026-10-01,7,8,ok\nA2,yas,2026-10-02,3,,\n');
    ok(r.out.textContent.includes('Structure plausible'), 'import: CSV correct reconnu');
    eq(r.out.querySelectorAll('tbody tr').length, 2, 'import: aperçu des lignes');
    eq(r.submit.disabled, false, 'import: bouton actif');
    ok(r.out.textContent.includes('2 colonne(s) de notes'), 'import: colonnes de notes comptées');
  }
  {
    const r = await preview('semi.csv', HEAD.replace(/,/g, ';') + 'A1;orange;2026-10-01;7;8;ok\n');
    ok(r.out.textContent.includes('séparateur « ; »'), 'import: séparateur point-virgule détecté');
  }
  {
    const r = await preview('bad.csv', 'external_id,collected_at,score_customer_service\nA,2026-10-01,5\n');
    ok(r.out.textContent.includes('operator_code'), 'import ARTEC: operator_code manquant signalé');
    eq(r.submit.disabled, true, 'import ARTEC: envoi bloqué si colonne obligatoire absente');
  }
  {
    const r = await preview('noscore.csv', 'operator_code,collected_at\norange,2026-10-01\n');
    ok(r.out.textContent.includes('Aucune colonne de note'), 'import: aucune colonne de notes signalée'); eq(r.submit.disabled, true, 'import: envoi bloqué');
  }
  {
    const r = await preview('unk.csv', HEAD.trim() + ',bogus\nA,orange,2026-10-01,5,5,x,zzz\n');
    ok(r.out.textContent.includes('bogus'), 'import: colonne inconnue signalée'); eq(r.submit.disabled, false, 'import: colonnes inconnues = avertissement seulement');
  }
  {
    const r = await preview('virus.exe', 'MZ'); ok(r.out.textContent.includes('Format refusé'), 'import: extension refusée'); eq(r.submit.disabled, true, 'import: envoi bloqué');
    const x = await preview('d.xlsx', 'PK'); ok(x.out.textContent.includes('Aperçu non disponible pour Excel'), 'import: Excel -> information honnête'); eq(x.submit.disabled, false, 'import: xlsx autorisé');
    const big = await preview('big.csv', HEAD, { size: 11 * 1024 * 1024 }); ok(big.out.textContent.includes('trop volumineux'), 'import: taille > 10 Mo refusée'); eq(big.submit.disabled, true, 'import: envoi bloqué');
    const empty = await preview('e.csv', ''); ok(empty.out.textContent.includes('vide'), 'import: fichier vide signalé');
  }
  {
    const r = await preview('xss.csv', HEAD + '"<img src=x onerror=alert(1)>",orange,2026-10-01,5,5,"<script>alert(1)</script>"\n');
    eq(r.out.querySelectorAll('img, script').length, 0, 'sécurité: contenu du fichier jamais interprété comme HTML (aperçu)');
    ok(r.out.textContent.includes('<img src=x'), 'sécurité: affiché comme texte');
  }

  /* ---------- Confirmation, chargement, filtre ---------- */
  {
    const w = await load('feedback_list', ['../vendor/bootstrap/js/bootstrap.bundle.min.js', 'core.js']);
    const form = q(w, 'form[action*="validation"]'); const btn = form.querySelector('button[value="reject"]');
    const ev = submit(w, form, btn);
    eq(ev.defaultPrevented, true, 'confirmation: la soumission est suspendue');
    ok(q(w, '[data-confirm-message]').textContent.includes('Rejeter cet avis'), 'confirmation: message spécifique du bouton cliqué');
    let called = null; form.requestSubmit = s => { called = s; };
    click(w, q(w, '[data-confirm-accept]'));
    eq(form.dataset.confirmed, '1', 'confirmation: validée'); eq(called && called.value, 'reject', 'confirmation: renvoie avec le bouton d’origine (decision=reject conservé)');
  }
  {
    const w = await load('<html><body><div class="ar-loading-bar"></div><input data-table-filter="#t" data-filter-count="#n"><span id="n"></span><table id="t"><tbody><tr><td>Orange réclamation</td></tr><tr><td>Yas import</td></tr><tr><td>Airtel avis</td></tr></tbody></table></body></html>', ['core.js']);
    const i = q(w, 'input'); i.value = 'YAS'; i.dispatchEvent(new w.Event('input'));
    eq(qa(w, 'tbody tr').filter(r => !r.hidden).length, 1, 'filtre de tableau: insensible à la casse');
    ok(q(w, '#n').textContent.startsWith('1 ligne'), 'filtre de tableau: compteur annoncé');
    i.value = ''; i.dispatchEvent(new w.Event('input')); eq(qa(w, 'tbody tr').filter(r => r.hidden).length, 0, 'filtre de tableau: réinitialisation');
  }
  {
    const w = await load('<html><body><div class="ar-offline"></div></body></html>', ['core.js']);
    ok(!q(w, '.ar-offline').classList.contains('is-visible'), 'hors-ligne: bannière masquée en ligne');
    Object.defineProperty(w.navigator, 'onLine', { value: false, configurable: true }); w.dispatchEvent(new w.Event('offline'));
    ok(q(w, '.ar-offline').classList.contains('is-visible'), 'hors-ligne: bannière affichée');
  }

  console.log(`\nJS : ${passed} vérifications réussies, ${failed} échec(s).`);
  if (failed) { failures.forEach(f => console.log('  ✗ ' + f)); process.exit(1); }
})().catch(e => { console.error('ERREUR HARNAIS', e); process.exit(2); });
