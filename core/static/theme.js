// ポケクル 配色の切り替え(全ページ共有。core/static/theme.css とセットで使う)。
// このファイルは読み込みを待たなくてよい(初回ペイント前の適用は各ページ <head> 先頭の
// インラインスクリプト = THEME_BOOT_SNIPPET と同文面が既に済ませている。ここでは:
//   - localStorage の値と端末配色を突き合わせて data-theme を確定させ直す(保険。二重に呼んでも安全)
//   - 端末の配色が変わった(prefers-color-scheme の変化。「端末に合わせる」選択時だけ効く)ときに追従
//   - window.TP_THEME を公開する(index.html の惑星キャンバスが毎フレーム .mode を読む)
//   - ⋯メニュー(#homeMenu。index.html にだけ存在)に「表示: 端末に合わせる/ライト/ダーク」を配線する
(function () {
  var KEY = 'tp.theme';   // 値は 'auto' | 'light' | 'dark'。読めない/壊れているときは 'auto' 扱い
  var mq = null;
  try { mq = window.matchMedia('(prefers-color-scheme: light)'); } catch (e) { mq = null; }

  function getPref() {
    try {
      var v = localStorage.getItem(KEY);
      return (v === 'light' || v === 'dark') ? v : 'auto';
    } catch (e) { return 'auto'; }
  }
  function deviceIsLight() {
    try { return !!(mq && mq.matches); } catch (e) { return false; }
  }
  function resolve(pref) {
    return pref === 'light' || pref === 'dark' ? pref : (deviceIsLight() ? 'light' : 'dark');
  }
  function apply(pref) {
    var mode = resolve(pref);
    try { document.documentElement.setAttribute('data-theme', mode); } catch (e) {}
    window.TP_THEME.pref = pref;
    window.TP_THEME.mode = mode;
    updateMenuUI(pref);
    return mode;
  }
  function setPref(pref) {
    try {
      if (pref === 'auto') localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, pref);
    } catch (e) { /* ストレージが使えない端末でも画面は動かす(見た目がその場で変わるだけ) */ }
    return apply(pref);
  }

  // <meta name="theme-color"> は media 属性つきの2枚(dark/light)を各ページに置いてあり、
  // ステータスバーの色は端末配色にそのまま追従する(既知の制約: ⋯メニューで端末と逆の配色を
  // 明示選択した場合、ステータスバーだけは端末側の配色のままになる。OS側APIの制約のため)。
  function updateMenuUI(pref) {
    var row = document.getElementById('themeRow'); if (!row) return;
    var btns = row.querySelectorAll('[data-theme-opt]');
    for (var i = 0; i < btns.length; i++) {
      btns[i].classList.toggle('on', btns[i].getAttribute('data-theme-opt') === pref);
    }
  }

  window.TP_THEME = { pref: getPref(), mode: resolve(getPref()), setPref: setPref, KEY: KEY };
  apply(getPref());   // 保険の再適用(ブート用スニペットと重複しても副作用なし)

  if (mq) {
    var onChange = function () { if (getPref() === 'auto') apply('auto'); };
    try { mq.addEventListener('change', onChange); } catch (e) { try { mq.addListener(onChange); } catch (e2) {} }
  }

  document.addEventListener('DOMContentLoaded', function () {
    updateMenuUI(getPref());
    var row = document.getElementById('themeRow'); if (!row) return;
    row.addEventListener('click', function (e) {
      var b = e.target.closest('[data-theme-opt]'); if (!b) return;
      e.stopPropagation();
      setPref(b.getAttribute('data-theme-opt'));
    });
  });
})();
