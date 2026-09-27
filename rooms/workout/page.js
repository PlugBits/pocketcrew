// ポケクル /workout: log.md 由来のグラフ・一覧を描く。グラフは全部インライン SVG(外部ライブラリ不可)。
window.tpWorkout = (() => {
const escSafe = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const KG_PER_LB = 0.45359;
const WDJ = ['日', '月', '火', '水', '木', '金', '土'];
let data = null, selectedExercise = null;
try { selectedExercise = localStorage.getItem('wk.exercise') || null; } catch (e) {}
try { const qp = new URLSearchParams(location.search).get('ex'); if (qp) selectedExercise = qp; } catch (e) {}

function numFmt(n) {
  const v = Number(n);
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}
function toKg(lb) { return (Number(lb) * KG_PER_LB).toFixed(1); }
function dObj(iso) { return new Date(iso + 'T00:00:00'); }
function fmtD(iso) { const d = dObj(iso); return `${d.getMonth() + 1}/${d.getDate()}`; }
function fmtDW(iso) { const d = dObj(iso); return `${d.getMonth() + 1}/${d.getDate()}(${WDJ[d.getDay()]})`; }

// ---- インライン SVG 折れ線グラフ ----
// points: [{date, value, ...extra}] (日付は昇順でなくてよい。内部でソートする)
function lineChart(points, opts) {
  opts = Object.assign({
    w: 640, h: 200, padL: 34, padR: 20, padTop: 26, padBottom: 20,
    color: 'var(--acc)', radius: 4.5, showLabels: true, belowDate: true,
    belowLabel: null, valueFmt: c => numFmt(c.value), thinAbove: 12,
    kgAxis: false,
  }, opts || {});
  const { w, h, padL, padR, padTop, color, radius, showLabels, belowDate, belowLabel, valueFmt, thinAbove, kgAxis } = opts;
  let padBottom = opts.padBottom;
  if (showLabels && belowDate) padBottom = Math.max(padBottom, belowLabel ? 70 : 28);
  const x0 = padL, x1 = w - padR, y0 = padTop, y1 = h - padBottom;
  if (!points.length) return '<div class="none">データなし</div>';
  const sorted = [...points].sort((a, b) => a.date.localeCompare(b.date));
  const ts = sorted.map(p => dObj(p.date).getTime());
  const vals = sorted.map(p => Number(p.value));
  const tsMin = Math.min(...ts), tsMax = Math.max(...ts), tsSpan = tsMax - tsMin;
  let vMin = Math.min(...vals), vMax = Math.max(...vals);
  if (vMin === vMax) { const pad = Math.max(1, Math.abs(vMin) * 0.2); vMin -= pad; vMax += pad; }
  else { const pad = (vMax - vMin) * 0.18; vMin -= pad; vMax += pad; }
  const xs = t => sorted.length === 1 ? (x0 + x1) / 2 : x0 + (t - tsMin) / tsSpan * (x1 - x0);
  const ys = v => y1 - (v - vMin) / (vMax - vMin) * (y1 - y0);
  const coords = sorted.map((p, i) => ({ ...p, x: xs(ts[i]), y: ys(Number(p.value)) }));
  const gid = 'wkg' + Math.random().toString(36).slice(2, 8);
  let svg = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" style="width:100%;height:${h}px">`;
  svg += `<defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">`
       + `<stop offset="0%" stop-color="${color}" stop-opacity=".3"/><stop offset="100%" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>`;
  svg += `<line x1="${x0}" y1="${y1}" x2="${x1}" y2="${y1}" stroke="var(--line)" stroke-width="1"/>`;
  if (coords.length > 1) {
    const path = 'M' + coords.map(c => `${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(' L ');
    const area = path + ` L ${coords[coords.length - 1].x.toFixed(1)} ${y1} L ${coords[0].x.toFixed(1)} ${y1} Z`;
    svg += `<path d="${area}" fill="url(#${gid})" stroke="none"/>`;
    svg += `<path d="${path}" fill="none" stroke="${color}" stroke-width="2"/>`;
  }
  if (kgAxis) {
    svg += `<text x="${x1}" y="${(y0 - 8).toFixed(1)}" font-size="10" fill="var(--dim)" text-anchor="end">${toKg(vMax)} kg</text>`;
  }
  const step = coords.length > thinAbove ? Math.ceil(coords.length / thinAbove) : 1;
  // 端の点はラベルが viewBox からはみ出て切れるので anchor を寄せる。近接点はラベルを2段に互い違いにして重なりを避ける。
  const anchorFor = i => i === 0 ? 'start' : (i === coords.length - 1 ? 'end' : 'middle');
  coords.forEach((c, i) => {
    const anchor = anchorFor(i);
    svg += `<circle cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(1)}" r="${radius}" fill="${color}" class="pt" data-i="${i}"><title>${escSafe(fmtDW(c.date))} ${escSafe(valueFmt(c))}${c.name ? ' ' + escSafe(c.name) : ''}</title></circle>`;
    if (showLabels && (i % step === 0 || i === coords.length - 1)) {
      svg += `<text x="${c.x.toFixed(1)}" y="${(c.y - radius - 7).toFixed(1)}" font-size="11" fill="var(--fg)" text-anchor="${anchor}">${escSafe(valueFmt(c))}</text>`;
      if (belowDate) {
        const row = belowLabel ? (i % 2) * 26 : 0;
        svg += `<text x="${c.x.toFixed(1)}" y="${(y1 + 16 + row).toFixed(1)}" font-size="10" fill="var(--dim)" text-anchor="${anchor}">${escSafe(fmtD(c.date))}</text>`;
        if (belowLabel) {
          const t = belowLabel(c);
          if (t) svg += `<text x="${c.x.toFixed(1)}" y="${(y1 + 29 + row).toFixed(1)}" font-size="9.5" fill="var(--dim)" text-anchor="${anchor}">${escSafe(t)}</text>`;
        }
      }
    }
  });
  svg += '</svg>';
  return svg;
}

function sparkline(points) {
  return lineChart(points, { h: 44, padL: 4, padR: 4, padTop: 6, padBottom: 6, radius: 2.6, showLabels: false });
}

// ---- 種目ごとのグラフ(専用・数字は最小限) ----
// グラフの中には値ラベル(整数)と日付(M/D)以外の文字は置かない。
function exerciseChart(points) {
  const w = 640, h = 170, padL = 32, padR = 14, padTop = 24, padBottom = 24;
  const x0 = padL, x1 = w - padR, y0 = padTop, y1 = h - padBottom;
  if (!points.length) return '<div class="none">データなし</div>';
  const sorted = [...points].sort((a, b) => a.date.localeCompare(b.date));
  const ts = sorted.map(p => dObj(p.date).getTime());
  const vals = sorted.map(p => Number(p.value));
  const tsMin = Math.min(...ts), tsMax = Math.max(...ts), tsSpan = tsMax - tsMin || 1;
  const vLo = Math.min(...vals), vHi = Math.max(...vals);
  let vMin, vMax;
  if (vLo === vHi) { vMin = vLo * 0.85; vMax = vHi * 1.15; }
  else { vMin = vLo * 0.9; vMax = vHi * 1.1; }
  const xs = t => sorted.length === 1 ? (x0 + x1) / 2 : x0 + (t - tsMin) / tsSpan * (x1 - x0);
  const ys = v => y1 - (v - vMin) / (vMax - vMin) * (y1 - y0);
  const coords = sorted.map((p, i) => ({ ...p, x: xs(ts[i]), y: ys(Number(p.value)) }));
  const gid = 'wkex' + Math.random().toString(36).slice(2, 8);

  let svg = `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" style="width:100%;height:${h}px">`;
  svg += `<defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">`
       + `<stop offset="0%" stop-color="var(--acc)" stop-opacity=".25"/><stop offset="100%" stop-color="var(--acc)" stop-opacity="0"/></linearGradient></defs>`;
  svg += `<text x="${x0}" y="${(padTop - 10).toFixed(1)}" font-size="10" fill="var(--dim)">推定1RM (lb)</text>`;
  // 横の薄い罫線3本 + 左端の軸値(整数)を3つだけ
  for (let i = 0; i < 3; i++) {
    const frac = i / 2;
    const gy = y0 + frac * (y1 - y0);
    const gv = Math.round(vMax - frac * (vMax - vMin));
    svg += `<line x1="${x0}" y1="${gy.toFixed(1)}" x2="${x1}" y2="${gy.toFixed(1)}" stroke="var(--line)" stroke-width="1"/>`;
    svg += `<text x="${(x0 - 6).toFixed(1)}" y="${(gy + 3).toFixed(1)}" font-size="9.5" fill="var(--dim)" text-anchor="end">${gv}</text>`;
  }
  if (coords.length > 1) {
    const path = 'M' + coords.map(c => `${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(' L ');
    const area = path + ` L ${coords[coords.length - 1].x.toFixed(1)} ${y1} L ${coords[0].x.toFixed(1)} ${y1} Z`;
    svg += `<path d="${area}" fill="url(#${gid})" stroke="none"/>`;
    svg += `<path d="${path}" fill="none" stroke="var(--acc)" stroke-width="2"/>`;
  }
  const maxDates = 12;
  const step = coords.length > maxDates ? Math.ceil(coords.length / maxDates) : 1;
  const avgGap = coords.length > 1 ? (x1 - x0) / (coords.length - 1) : (x1 - x0);
  const alternate = avgGap < 40 && coords.length > 2;
  coords.forEach((c, i) => {
    svg += `<circle cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(1)}" r="5" fill="var(--acc)" class="pt" data-i="${i}"><title>${escSafe(fmtDW(c.date))} ${escSafe(Math.round(c.value))}</title></circle>`;
    const nearRight = c.x > x1 - 24;
    const anchor = nearRight ? 'end' : 'start';
    const lx = nearRight ? c.x - 7 : c.x + 7;
    const flip = alternate && (i % 2 === 1);
    const ly = flip ? c.y + 16 : c.y - 10;
    svg += `<text x="${lx.toFixed(1)}" y="${ly.toFixed(1)}" font-size="11" font-weight="700" fill="var(--fg)" text-anchor="${anchor}">${Math.round(c.value)}</text>`;
    if (i % step === 0 || i === coords.length - 1) {
      svg += `<text x="${c.x.toFixed(1)}" y="${(h - 8).toFixed(1)}" font-size="10" fill="var(--dim)" text-anchor="middle">${escSafe(fmtD(c.date))}</text>`;
    }
  });
  svg += '</svg>';
  return svg;
}

// ---- 種目ごとの一覧(新しい順に最大8行・前回比つき) ----
function renderExList(entries) {
  const sorted = [...entries].sort((a, b) => a.date.localeCompare(b.date));
  const withDiff = sorted.map((e, i) => ({
    ...e,
    diff: i === 0 ? null : Math.round((e.e1rm - sorted[i - 1].e1rm) * 10) / 10,
  }));
  const rows = withDiff.slice(-8).reverse();
  if (!rows.length) return '<div class="none">記録がありません</div>';
  return rows.map(e => {
    let diffHtml;
    if (e.diff === null || e.diff === 0) diffHtml = '<span class="diff flat">—</span>';
    else if (e.diff > 0) diffHtml = `<span class="diff ok">↑ +${escSafe(numFmt(e.diff))}</span>`;
    else diffHtml = `<span class="diff warn">↓ ${escSafe(numFmt(e.diff))}</span>`;
    return `<div class="ex-row"><span class="d">${escSafe(fmtD(e.date))}</span><span class="sep">·</span>`
      + `<span class="wr">${escSafe(numFmt(e.best_lb))} lb × ${escSafe(numFmt(e.best_reps))}</span><span class="sep">·</span>`
      + `<span class="e1">推定1RM ${escSafe(Math.round(e.e1rm))}</span> <span class="kg2">(${toKg(e.e1rm)} kg)</span><span class="sep">·</span>`
      + diffHtml + `</div>`;
  }).join('');
}

// ---- 直近の PR ----
function renderPRs() {
  const el = document.getElementById('wk-prList');
  const list = (data.prs || []).slice(0, 5);
  if (!list.length) { el.innerHTML = '<div class="none">まだ PR はありません</div>'; return; }
  el.innerHTML = list.map(p => `<div class="pr-item"><span class="d">${escSafe(fmtD(p.date))}</span>`
    + `<span class="ex">${escSafe(p.exercise)}</span>`
    + `<span class="w">${escSafe(numFmt(p.prev_lb))}→${escSafe(numFmt(p.lb))} lb ×${escSafe(numFmt(p.reps))}<span class="kgtxt">(${toKg(p.lb)} kg)</span></span></div>`).join('');
}

// ---- 総重量の推移 ----
function renderTrend() {
  const el = document.getElementById('wk-trend');
  const points = (data.workouts || []).map(w => ({ date: w.date, value: w.total_lb, name: w.name }));
  if (!points.length) { el.innerHTML = '<div class="none">記録がありません</div>'; return; }
  el.innerHTML = lineChart(points, {
    h: 230, color: 'var(--acc)', kgAxis: true,
    valueFmt: c => `${numFmt(c.value)} lb`,
    belowLabel: c => c.name,
  });
  el.innerHTML += `<div class="kgnote">右上の数字は最高値の kg 換算</div>`;
}

// ---- 種目ごとのベスト重量 ----
function exerciseRank() {
  // [name, entries] を記録日数降順・同数は名前順でソート
  return Object.entries(data.exercises || {})
    .map(([name, entries]) => ({ name, entries: [...entries].sort((a, b) => a.date.localeCompare(b.date)) }))
    .sort((a, b) => (b.entries.length - a.entries.length) || a.name.localeCompare(b.name, 'ja'));
}

function renderExerciseSection() {
  const ranked = exerciseRank();
  const selEl = document.getElementById('wk-exSelect');
  const chartEl = document.getElementById('wk-exChart');
  const listEl = document.getElementById('wk-exList');
  const gridEl = document.getElementById('wk-sparkGrid');
  if (!ranked.length) {
    selEl.innerHTML = ''; chartEl.innerHTML = '<div class="none">記録がありません</div>'; listEl.innerHTML = ''; gridEl.innerHTML = '';
    return;
  }
  if (!selectedExercise || !ranked.some(r => r.name === selectedExercise)) selectedExercise = ranked[0].name;
  try { localStorage.setItem('wk.exercise', selectedExercise); } catch (e) {}
  selEl.innerHTML = ranked.map(r => `<option value="${escSafe(r.name)}"${r.name === selectedExercise ? ' selected' : ''}>${escSafe(r.name)} (${r.entries.length}回)</option>`).join('');
  const cur = ranked.find(r => r.name === selectedExercise);
  const points = cur.entries.map(e => ({ date: e.date, value: e.e1rm, lb: e.best_lb, reps: e.best_reps }));
  chartEl.innerHTML = exerciseChart(points);
  listEl.innerHTML = renderExList(cur.entries);

  // ミニカード: 自重(推定1RM 0)は除き、伸び幅の大きい順に 4 つ(同じなら記録日数順)
  const top4 = ranked.filter(r => r.entries.length >= 2 && r.entries[r.entries.length - 1].e1rm > 0)
    .map(r => ({ r, d: Math.abs(r.entries[r.entries.length - 1].e1rm - r.entries[0].e1rm) }))
    .sort((a, b) => b.d - a.d || b.r.entries.length - a.r.entries.length).slice(0, 4).map(x => x.r);
  if (!top4.length) { gridEl.innerHTML = ''; return; }
  gridEl.innerHTML = top4.map(r => {
    const first = r.entries[0], last = r.entries[r.entries.length - 1];
    const pts = r.entries.map(e => ({ date: e.date, value: e.e1rm }));
    const diff = Math.round((last.e1rm - first.e1rm) * 10) / 10;
    const cls = diff > 0 ? 'ok' : diff < 0 ? 'warn' : '';
    const arrow = diff > 0 ? '↑' : diff < 0 ? '↓' : '';
    const deltaTxt = diff !== 0 ? `${arrow}${diff > 0 ? '+' : ''}${numFmt(diff)}` : '';
    return `<div class="spark-card" data-ex="${escSafe(r.name)}"><div class="nm">${escSafe(r.name)}</div>${sparkline(pts)}`
      + `<div class="rng">${escSafe(numFmt(first.e1rm))} → ${escSafe(numFmt(last.e1rm))} lb`
      + (cls ? ` <span class="delta ${cls}">${escSafe(deltaTxt)}</span>` : '')
      + `</div></div>`;
  }).join('');
}

// ---- 継続と成長(今週・連続・上がった種目) ----
function renderKpi() {
  const kpi = data.kpi || {};
  const weeks = kpi.weeks || [];
  document.getElementById('wk-kpiWeekNum').textContent = kpi.this_week != null ? kpi.this_week : '–';
  document.getElementById('wk-kpiWeeks').innerHTML = weeks.map(w =>
    `<span class="sq ${w.count >= 2 ? 'c2' : w.count === 1 ? 'c1' : ''}" title="${escSafe(fmtD(w.start))} ${w.count}回"></span>`
  ).join('');
  const datesEl = document.getElementById('wk-kpiWeekDates');
  datesEl.innerHTML = weeks.length
    ? `<span>${escSafe(fmtD(weeks[0].start))}</span><span>${escSafe(fmtD(weeks[weeks.length - 1].start))}</span>`
    : '';
  const streak = kpi.streak_weeks || 0;
  const streakWrap = document.getElementById('wk-kpiStreakWrap');
  streakWrap.innerHTML = streak > 0
    ? `<div class="kpi-num">${streak}</div><div class="kpi-lbl">週連続</div>`
    : `<div class="kpi-empty">今週まだ</div>`;
  const imp = kpi.improved || { up: 0, total: 0 };
  document.getElementById('wk-kpiImpNum').textContent = `${imp.up}/${imp.total}`;
}

// ---- 頻度 ----
function freqBlock(title, bucket) {
  const names = Object.entries(bucket.by_name || {});
  const parts = Object.entries(bucket.by_part || {});
  if (!names.length) return `<div class="freq-block"><div class="freq-title">${escSafe(title)}(${escSafe(bucket.month)})</div><div class="none">記録がありません</div></div>`;
  const maxN = Math.max(...names.map(x => x[1]), 1);
  const maxP = Math.max(...parts.map(x => x[1]), 1);
  const row = (max) => ([n, c]) => `<div class="freq-row"><span class="nm">${escSafe(n)}</span><span class="bar"><i style="width:${(c / max * 100).toFixed(0)}%"></i></span><span class="n">${c}回</span></div>`;
  return `<div class="freq-block"><div class="freq-title">${escSafe(title)}(${escSafe(bucket.month)})・メニュー別</div>${names.map(row(maxN)).join('')}`
    + `<div class="freq-title" style="margin-top:8px">${escSafe(title)}・部位別</div>${parts.map(row(maxP)).join('')}</div>`;
}
function renderFreq() {
  const el = document.getElementById('wk-freq');
  el.innerHTML = freqBlock('今月', data.freq.this_month) + freqBlock('先月', data.freq.last_month);
}

// ---- 記録一覧 ----
function renderRecords() {
  const el = document.getElementById('wk-recList');
  const list = data.workouts || [];
  if (!list.length) { el.innerHTML = '<div class="none">記録がありません</div>'; return; }
  el.innerHTML = list.map((w, i) => `<div class="rec" data-i="${i}">`
    + `<div class="hd"><span class="d">${escSafe(fmtDW(w.date))}</span><span class="nm">${escSafe(w.name)}</span>`
    + `<span class="tot">${escSafe(numFmt(w.total_lb))} lb<small> (${toKg(w.total_lb)} kg)</small>${w.pr ? `<span class="pr-sm">PR${w.pr}</span>` : ''}</span></div>`
    + `<div class="meta">${w.duration_min != null ? `時間 ${w.duration_min}分` : ''}</div>`
    + `<div class="ex-detail">${w.exercises.map(e => `<div><span class="exn">${escSafe(e.name)}</span> ${escSafe(numFmt(e.best.lb))} lb×${escSafe(numFmt(e.best.reps))}`
      + ` <span style="opacity:.75">(${e.sets.map(s => `${numFmt(s.lb)}×${numFmt(s.reps)}`).join(', ')})</span></div>`).join('')}</div>`
    + `</div>`).join('');
  el.querySelectorAll('.rec .hd').forEach(hd => hd.addEventListener('click', () => hd.closest('.rec').classList.toggle('open')));
}

// ---- CSV 取り込みボタン ----
function renderImportBtn() {
  const btn = document.getElementById('wk-import');
  const n = data.inbox_csv || 0;
  btn.disabled = n === 0;
  btn.textContent = n > 0 ? `CSV を取り込む (${n})` : 'CSV を取り込む';
}

function render() {
  renderImportBtn();
  renderKpi();
  renderPRs();
  renderTrend();
  renderExerciseSection();
  renderFreq();
  renderRecords();
}

async function load() {
  data = await (await fetch('/api/workout', { cache: 'no-store' })).json();
  render();
}

document.getElementById('wk-kpiImproved').addEventListener('click', () => {
  document.getElementById('wk-exSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
});

document.getElementById('wk-exSelect').addEventListener('change', e => {
  selectedExercise = e.target.value;
  renderExerciseSection();
});

function stepExercise(delta) {
  const ranked = exerciseRank();
  if (!ranked.length) return;
  const idx = Math.max(0, ranked.findIndex(r => r.name === selectedExercise));
  selectedExercise = ranked[(idx + delta + ranked.length) % ranked.length].name;
  renderExerciseSection();
}
document.getElementById('wk-exPrev').addEventListener('click', () => stepExercise(-1));
document.getElementById('wk-exNext').addEventListener('click', () => stepExercise(1));

document.getElementById('wk-sparkGrid').addEventListener('click', e => {
  const card = e.target.closest('.spark-card[data-ex]');
  if (!card) return;
  selectedExercise = card.dataset.ex;
  renderExerciseSection();
  document.getElementById('wk-exSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
});

document.getElementById('wk-import').addEventListener('click', async () => {
  const btn = document.getElementById('wk-import');
  btn.disabled = true; btn.textContent = '取り込み中…';
  try {
    const res = await (await fetch('/api/workout/import', { method: 'POST' })).json();
    const n = (res.results || []).reduce((s, r) => s + (r.workouts || 0), 0);
    btn.textContent = `取り込み完了(${n}件)`;
  } catch (e) {
    btn.textContent = '失敗しました';
  }
  await load();
});

load();
return { load };
})();
