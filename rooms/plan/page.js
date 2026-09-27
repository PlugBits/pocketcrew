// ポケクル plan: /plan と 司令室内のパネルで共用
// 数字タブは rooms-private/numbers(tab_in="plan")に移設。ここには「タブ機構」だけが残る。
window.tpPlan=(()=>{
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const WD='日月火水木金土';
let data=null;

// このスクリプト自身の src="/plan.js?v=<version>" から version を読む(同期実行中でないと
// document.currentScript が取れないので、ファイル先頭・await の前で確保しておく)。
const SHELL_V=(()=>{
  try{
    const src=document.currentScript&&document.currentScript.src;
    if(src){ const m=src.match(/[?&]v=([^&]+)/); if(m) return m[1]; }
  }catch(e){}
  return '';
})();

// ---------- 汎用ヘルパ ----------
function fmtD(iso){const d=new Date(iso+'T00:00:00');return `${d.getMonth()+1}/${d.getDate()}`;}
function fmtDday(iso){const d=new Date(iso+'T00:00:00');return `${d.getMonth()+1}/${d.getDate()} ${WD[d.getDay()]}`;}
function addDays(iso,n){const d=new Date(iso+'T00:00:00');d.setDate(d.getDate()+n);return d.toISOString().slice(0,10);}
function daysBetween(a,b){return Math.round((new Date(b+'T00:00:00')-new Date(a+'T00:00:00'))/86400000);}

// ---------- タブ(セグメントコントロール + ハッシュ連動 + プラグイン差し込み) ----------
// 組み込みタブの並び順。plan-private の「数字」タブは 30 で登録される(今日10/タスク20/数字30/ゴール40/ログ50)。
const TAB_ORDER={today:10, tasks:20, goals:40, log:50};
const onShowMap={};
function orderOf(id){ return TAB_ORDER[id]!=null?TAB_ORDER[id]:100; }
function tabButtons(){ return [...document.querySelectorAll('#plan-root .tabs button')]; }
function tabIds(){ return tabButtons().map(b=>b.dataset.t); }

function positionTabHl(){
  const tabs=tabButtons();
  const hl=document.getElementById('pl-tabHl'); if(!hl) return;
  const n=tabs.length||1;
  hl.style.width=`calc((100% - 6px)/${n})`;
  const idx=tabs.findIndex(b=>b.classList.contains('on'));
  if(idx>=0) hl.style.transform=`translateX(${idx*100}%)`;
}
function selectTab(t,skipHash){
  if(!tabIds().includes(t)) t='today';
  document.querySelectorAll('#plan-root .tabs button').forEach(b=>b.classList.toggle('on',b.dataset.t===t));
  document.querySelectorAll('#plan-root section').forEach(s=>s.classList.toggle('on',s.id==='pl-'+t));
  positionTabHl();
  try{localStorage.setItem('tp.plantab',t);}catch(e){}
  if(!skipHash){ try{ if(location.hash!=='#tab='+t) history.replaceState(null,'',location.pathname+'#tab='+t); }catch(e){} }
  const onShow=onShowMap[t];
  if(onShow){ const sec=document.getElementById('pl-'+t); if(sec){ try{ onShow(sec); }catch(e){} } }
}
function attachTabClick(btn){ btn.addEventListener('click',()=>selectTab(btn.dataset.t)); }
tabButtons().forEach(attachTabClick);
function tabFromHash(){const m=location.hash.match(/tab=([a-z0-9_-]+)/i); return m?m[1]:null;}
window.addEventListener('hashchange',()=>{const t=tabFromHash(); if(t) selectTab(t,true);});
addEventListener('resize',positionTabHl);
{
  let initTab=tabFromHash();
  if(!initTab){ try{ initTab=localStorage.getItem('tp.plantab'); }catch(e){} }
  selectTab(initTab||'today',true);
}

// 並び順(order)を守って、コンテナの直接の子(selector に一致するもの)の中に要素を挿す
function insertOrdered(container, selector, el, id){
  const siblings=[...container.querySelectorAll(':scope > '+selector)];
  const myOrder=orderOf(id);
  let ref=null;
  for(const s of siblings){
    const sid=s.dataset&&s.dataset.t!=null?s.dataset.t:s.id.replace(/^pl-/,'');
    if(orderOf(sid)>myOrder){ ref=s; break; }
  }
  if(ref) container.insertBefore(el,ref); else container.appendChild(el);
}

// room(tab_in="plan")から呼ぶプラグインAPI。addTab({id,label,order,html,init,onShow})
// - タブボタン・<section id="pl-<id>"> を組み込みタブと同じ見た目・構造で order 順に差し込む
// - init(sectionEl) を1回、onShow(sectionEl) をそのタブを表示するたびに呼ぶ
// - #tab=<id> がすでに URL に付いていれば、登録直後にそのタブへ切り替える
function addTab({id,label,order,html,init,onShow}){
  if(!id||document.getElementById('pl-'+id)) return;
  TAB_ORDER[id]=order!=null?order:100;
  if(onShow) onShowMap[id]=onShow;
  const sec=document.createElement('section');
  sec.id='pl-'+id;
  sec.innerHTML=html||'';
  const btn=document.createElement('button');
  btn.dataset.t=id;
  btn.textContent=label||id;
  attachTabClick(btn);
  insertOrdered(document.querySelector('#plan-root .tabs'),'button',btn,id);
  insertOrdered(document.getElementById('plan-root'),'section',sec,id);
  positionTabHl();
  if(init){ try{ init(sec); }catch(e){} }
  if(tabFromHash()===id) selectTab(id,true);
}
window.TPPlan={addTab};

// /api/rooms を見て、tab_in="plan" の room の tab.js を読み込む(失敗しても組み込みタブだけで動く)
function loadScript(src){
  return new Promise((resolve,reject)=>{
    const s=document.createElement('script');
    s.src=src; s.onload=resolve; s.onerror=()=>reject(new Error('load failed: '+src));
    document.head.appendChild(s);
  });
}
async function loadRoomTabs(){
  let j;
  try{ j=await (await fetch('/api/rooms',{cache:'no-store'})).json(); }catch(e){ return; }
  for(const r of (j&&j.rooms)||[]){
    if(r.tab_in!=='plan'||!r.tab) continue;
    try{ await loadScript(r.tab+(SHELL_V?`?v=${SHELL_V}`:'')); }catch(e){}
  }
}

// ================= 今日・タスク・ゴール(vault/plan) =================
async function load(){data=await (await fetch('/api/plan',{cache:'no-store'})).json(); render();}
function render(){
  const dateEl=document.getElementById('pl-date'); if(dateEl) dateEl.textContent=`${fmtD(data.today)} ${data.weekday}`;
  renderToday();renderTasks();renderGoals();
}

function taskRowHtml(t){
  return `<div class="task" data-line="${t.line}"><div class="cb"></div><div class="tx">${esc(t.text)}${t.who?`<span class="chip who">@${esc(t.who)}</span>`:''}</div></div>`;
}
function schedRowHtml(it){
  return `<div class="ev-row">${it.time?`<span class="tm">${esc(it.time)}</span>`:''}<span class="${it.repeat?'rp':''}">${esc(it.text)}</span>${it.repeat?'<span class="rpicon">↻</span>':''}</div>`;
}

function renderToday(){
  const {today,weekday,tasks,schedule}=data;
  document.getElementById('pl-todayBig').textContent=`${fmtD(today)} ${weekday}`;
  const overdueTasks=tasks.filter(t=>t.due&&!t.done&&t.overdue);
  const dueToday=tasks.filter(t=>t.due===today&&!t.done);
  const chips=[`<span class="chip">期限今日 ${dueToday.length}</span>`];
  if(overdueTasks.length) chips.push(`<span class="chip warn">超過 ${overdueTasks.length}</span>`);
  document.getElementById('pl-todayChips').innerHTML=chips.join('');

  const dueItems=tasks.filter(t=>t.due&&!t.done&&t.due>=today).map(t=>({date:t.due,time:'',kind:'task',...t}));
  // 毎日の繰り返しは今日以外では表示しない(60日ぶん並ぶと埋もれるため)
  const schedItems=schedule.filter(s=>s.repeat!=='daily'||s.date===today).map(s=>({...s,kind:'sch'}));
  const items=[...schedItems,...dueItems];
  const byDate={};
  for(const it of items){(byDate[it.date]=byDate[it.date]||[]).push(it);}
  const wkEnd=addDays(today,7);
  const dates=Object.keys(byDate).sort();
  let mainHtml='', laterHtml='';
  for(const d of dates){
    const rows=byDate[d].sort((a,b)=>(a.time||'').localeCompare(b.time||''))
      .map(it=>it.kind==='task'?taskRowHtml(it):schedRowHtml(it)).join('');
    const isToday=d===today;
    const block=`<div class="dategrp"><div class="dategrp-h ${isToday?'today':''}">${fmtDday(d)}${isToday?'(今日)':''}</div>${rows}</div>`;
    if(d<=wkEnd) mainHtml+=block; else laterHtml+=block;
  }
  let overdueHtml='';
  if(overdueTasks.length){
    overdueHtml=`<div class="dategrp"><div class="dategrp-h warn">期限超過</div>${overdueTasks.map(taskRowHtml).join('')}</div>`;
  }
  document.getElementById('pl-todayGroups').innerHTML=(overdueHtml+mainHtml)||'<div class="none">予定がありません</div>';
  const laterWrap=document.getElementById('pl-laterWrap');
  if(laterHtml){ laterWrap.hidden=false; document.getElementById('pl-laterList').innerHTML=laterHtml; }
  else { laterWrap.hidden=true; }
}
async function toggleLine(line){
  const j=await (await fetch('/api/plan/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({line})})).json();
  if(!j.ok){alert(j.error);return;}
  load();
}
document.getElementById('pl-todayGroups').addEventListener('click',e=>{const el=e.target.closest('.task[data-line]'); if(el) toggleLine(+el.dataset.line);});
document.getElementById('pl-taskList').addEventListener('click',e=>{const el=e.target.closest('.task[data-line]'); if(el) toggleLine(+el.dataset.line);});

function dueSoon(due){const n=daysBetween(data.today,due); return n>=0&&n<=3;}
function dueLabel(t){
  if(t.overdue){const n=daysBetween(t.due,data.today); return `${n}日超過`;}
  const n=daysBetween(data.today,t.due);
  if(n<0) return fmtD(t.due);
  if(n===0) return '今日';
  if(n<=3) return `あと${n}日`;
  return fmtD(t.due);
}
function renderTasks(){
  const byP={};
  for(const t of data.tasks) (byP[t.project]=byP[t.project]||[]).push(t);
  const html=Object.entries(byP).map(([p,arr])=>{
    const total=arr.length, undone=arr.filter(t=>!t.done), done=arr.filter(t=>t.done);
    const pct=total?Math.round((total-undone.length)/total*100):0;
    const sortKey=t=>t.overdue?0:(t.due?1:2);
    undone.sort((a,b)=>sortKey(a)-sortKey(b)||(a.due||'9999').localeCompare(b.due||'9999'));
    const row=t=>`<div class="task ${t.done?'done':''}" data-line="${t.line}"><div class="cb">${t.done?'✓':''}</div><div class="tx">${esc(t.text)}${t.due?`<span class="pill ${t.overdue?'warn':dueSoon(t.due)?'busy':'dim'}">${dueLabel(t)}</span>`:''}${t.who?`<span class="chip who">@${esc(t.who)}</span>`:''}</div></div>`;
    return `<div class="proj-card"><div class="proj-hd"><span class="nm">${esc(p)}</span><span class="cnt">未完了 ${undone.length} · 全 ${total}</span></div><div class="progress"><i style="width:${pct}%"></i></div><div class="tasklist">${undone.map(row).join('')||'<div class="none">未完了はありません</div>'}</div>${done.length?`<details><summary>完了 ${done.length}件</summary>${done.map(row).join('')}</details>`:''}</div>`;
  }).join('')||'<div class="none">tasks.md が空です</div>';
  document.getElementById('pl-taskList').innerHTML=html;
}

function ringSvg(pct){
  const r=18,c=2*Math.PI*r;
  const p=pct==null?0:Math.max(0,Math.min(100,pct));
  const dash=c*p/100;
  return `<svg width="44" height="44" viewBox="0 0 44 44"><circle cx="22" cy="22" r="${r}" fill="none" stroke="var(--line)" stroke-width="4"/><circle cx="22" cy="22" r="${r}" fill="none" stroke="var(--acc)" stroke-width="4" stroke-linecap="round" stroke-dasharray="${dash.toFixed(1)} ${c.toFixed(1)}" transform="rotate(-90 22 22)"/><text x="22" y="26" text-anchor="middle" font-size="12" fill="var(--fg)">${pct==null?'—':pct+'%'}</text></svg>`;
}
function renderGoals(){
  const html=(data.goals||[]).map((g,i)=>{
    const nd=g.due? daysBetween(data.today,g.due):null;
    const duePill=g.due?`<span class="pill ${nd<0?'warn':nd<=7?'busy':'dim'}">${nd<0?(-nd)+'日超過':'あと'+nd+'日'}</span>`:'';
    return `<div class="card goal-card" data-i="${i}"><div class="ring">${ringSvg(g.progress)}</div><div class="gbody"><div class="gt">${esc(g.title)}${duePill}</div><div class="kv">${g.metric?`指標 <b>${esc(g.metric)}</b><br>`:''}${g.now?`現在 <b>${esc(g.now)}</b>`:''}</div>${g.memo?`<div class="gmemo" hidden>${esc(g.memo)}</div>`:''}</div></div>`;
  }).join('')||'<div class="none">goals.md が空です</div>';
  document.getElementById('pl-goalList').innerHTML=html;
}
document.getElementById('pl-goalList').addEventListener('click',e=>{
  const card=e.target.closest('.goal-card'); if(!card) return;
  const memo=card.querySelector('.gmemo'); if(memo) memo.hidden=!memo.hidden;
});

// ---- ログ(当日) ----
async function loadLog(){try{const j=await (await fetch('/api/log',{cache:'no-store'})).json(); const el=document.getElementById('pl-logList'); if(!el) return;
  const items=[...j.items].reverse();
  const label=x=>x.kind==='key'?`⌨️ ${x.window} に ${x.key}`:x.kind==='new'?`＋ 新スレ ${x.name}${x.preset?`(${x.preset})`:''}`:x.kind==='restart'?`↻ 再起動 ${x.name||x.window}`:x.kind==='restore'?`↻ 復帰 ${x.name||x.window}`:x.kind==='forget'?`✕ 名簿から外す ${x.window}`:x.kind==='daily'?`📝 日次まとめを依頼(${x.day})`:x.kind==='notify'?`🔔 ${x.title} ${x.body||''}`:x.kind==='dismiss-survey'?`（アンケートを自動で閉じた: ${x.window}）`:x.text?`→ ${x.window}: ${x.text}`:JSON.stringify(x);
  el.innerHTML=items.length?`<div class="card">${items.map(x=>`<div class="logrow"><div class="dt">${esc((x.ts||'').slice(11,16))}</div><div class="ev" style="white-space:pre-wrap;word-break:break-word">${esc(label(x))}</div></div>`).join('')}</div>`:'<div class="none">今日はまだありません</div>';
}catch(e){}}

function loadAll(){load(); loadLog();}
loadAll(); document.addEventListener('visibilitychange',()=>{if(!document.hidden) loadAll();});
loadRoomTabs();
return {load:loadAll};
})();
