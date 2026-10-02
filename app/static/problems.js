let problemItems=[];
let problemSites=[];
let problemSiteByHost=new Map();

function problemCategory(p){
  const tags=p.tags||[];
  const preferred=['scope','class','component'];
  for(const key of preferred){const t=tags.find(x=>String(x.tag||'').toLowerCase()===key&&x.value);if(t)return String(t.value)}
  return 'other';
}
function problemHostNames(p){return (p.hosts||[]).map(h=>h.name||h.host).filter(Boolean)}
function problemSite(p){for(const h of problemHostNames(p)){const s=problemSiteByHost.get(h);if(s)return s}return null}
function scorePart(label,points,detail=''){if(!points)return '';return `<div class="score-part"><span>${esc(label)}</span><b>${points>0?'+':''}${points}</b>${detail?`<small>${esc(detail)}</small>`:''}</div>`}
function renderProblemDetails(p){
  const b=p.score_breakdown||{};
  const tagParts=(b.tags||[]).map(t=>scorePart(`${t.tag}=${t.value}`,Number(t.points)||0,'правило Score')).join('');
  const tags=(p.tags||[]).map(t=>`<span class="problem-tag">${esc(t.tag)}=${esc(t.value)}</span>`).join('')||'<span class="muted">Тегов нет</span>';
  const site=problemSite(p);
  return `<div class="problem-detail-card"><div class="problem-detail-head"><div><small>Event ID</small><b>${esc(p.eventid)}</b></div><div><small>Объект</small><b>${site?esc(site.site_key):'—'}</b></div><div><small>Начало</small><b>${new Date(p.started_at).toLocaleString('ru-RU')}</b></div><div><small>Итоговый Score</small><b class="score-total">${p.impact_score}</b></div></div><div class="problem-detail-section"><h3>Из чего складывается Score</h3><div class="score-parts">${scorePart('Severity',Number(b.severity)||0,sev[p.severity]||String(p.severity))}${tagParts}${scorePart('Длительность',Number(b.duration)||0,b.age_hours!=null?`${b.age_hours} ч`:'')}${scorePart('Не подтверждена',Number(b.unacknowledged)||0)}${!b.severity&&!tagParts&&!b.duration&&!b.unacknowledged?'<span class="muted">Расшифровка Score отсутствует. Выполните пересчёт Score.</span>':''}</div></div><div class="problem-detail-section"><h3>Теги Zabbix</h3><div class="problem-tags">${tags}</div></div></div>`
}
function initProblemFilters(){
  const site=$('#problemSite'),region=$('#problemRegion'),category=$('#problemCategory');
  if(site){const cur=site.value;site.innerHTML='<option value="">Все объекты</option>'+problemSites.map(x=>`<option value="${esc(x.site_key)}">${esc(x.site_key)}</option>`).join('');site.value=cur}
  if(region){const cur=region.value,items=[...new Set(problemSites.map(x=>x.region).filter(Boolean))].sort();region.innerHTML='<option value="">Все регионы</option>'+items.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('');region.value=items.includes(cur)?cur:''}
  if(category){const cur=category.value,items=[...new Set(problemItems.map(problemCategory))].sort();category.innerHTML='<option value="">Все категории</option>'+items.map(x=>`<option value="${esc(x)}">${esc(x)}</option>`).join('');category.value=items.includes(cur)?cur:''}
  ['problemSearch','problemSite','problemRegion','problemSeverity','problemCategory','problemScore'].forEach(id=>{const el=$('#'+id);if(el&&!el.dataset.ready){el.dataset.ready='1';el.addEventListener(id==='problemSearch'?'input':'change',applyProblemFilters)}})
}
function applyProblemFilters(){
  const q=($('#problemSearch')?.value||'').trim().toLowerCase(),site=$('#problemSite')?.value||'',region=$('#problemRegion')?.value||'',severity=$('#problemSeverity')?.value??'',category=$('#problemCategory')?.value||'',score=$('#problemScore')?.value??'';
  let items=problemItems.filter(p=>{const ps=problemSite(p),hosts=problemHostNames(p).join(' ');if(q&&!`${hosts} ${p.name||''}`.toLowerCase().includes(q))return false;if(site&&ps?.site_key!==site)return false;if(region&&ps?.region!==region)return false;if(severity!==''&&Number(p.severity)!==Number(severity))return false;if(category&&problemCategory(p)!==category)return false;if(score!==''&&Number(p.impact_score)<Number(score))return false;return true});
  items.sort((a,b)=>b.impact_score-a.impact_score||b.severity-a.severity||new Date(a.started_at)-new Date(b.started_at));
  renderProblems(items);const s=$('#problemFilterSummary');if(s)s.textContent=`Показано ${items.length} из ${problemItems.length} активных проблем`;
}
function renderProblems(items){
  $('#problemsBody').innerHTML=items.map((p,i)=>{const hosts=problemHostNames(p).join(', '),site=problemSite(p);return `<tr class="problem-row" onclick="toggleProblemDetails(${i})"><td><span class="problem-chevron" id="pc${i}">›</span><span class="risk risk-${p.impact_score>=70?'high':p.impact_score>=40?'mid':'low'}">${p.impact_score}</span></td><td>${sev[p.severity]||p.severity}</td><td><b>${esc(hosts)}</b>${site?`<small class="table-sub">${esc(site.site_key)}</small>`:''}</td><td>${esc(p.name)}</td><td>${esc(problemCategory(p))}</td><td>${age(p.started_at)}</td><td>${p.acknowledged?'Да':'Нет'}</td><td><button onclick="event.stopPropagation();deferProblem('${p.eventid}')">Отложить</button></td></tr><tr class="problem-details-row" id="p${i}" hidden><td colspan="8">${renderProblemDetails(p)}</td></tr>`}).join('')||'<tr><td colspan="8" class="empty">По выбранным фильтрам проблем нет</td></tr>';
}
function toggleProblemDetails(i){const row=$('#p'+i),ch=$('#pc'+i);if(!row)return;row.hidden=!row.hidden;if(ch)ch.classList.toggle('open',!row.hidden)}
function resetProblemFilters(){['problemSearch','problemSite','problemRegion','problemSeverity','problemCategory','problemScore'].forEach(id=>{const el=$('#'+id);if(el)el.value=''});applyProblemFilters()}
async function loadProblems(){
  try{const [d,s]=await Promise.all([api('/api/v1/problems?limit=1000'),api('/api/v1/sites')]);problemItems=d.items||[];problemSites=s.items||[];problemSiteByHost=new Map();problemSites.forEach(site=>(site.hosts||[]).forEach(h=>problemSiteByHost.set(h.name||h.host,site)));
    const high=problemItems.filter(x=>x.severity===4).length,disaster=problemItems.filter(x=>x.severity===5).length,unack=problemItems.filter(x=>!x.acknowledged).length;$('#cards').innerHTML=`<div class="card"><span class="muted">Активные проблемы</span><div class="number">${problemItems.length}</div></div><div class="card"><span class="muted">Disaster</span><div class="number">${disaster}</div></div><div class="card"><span class="muted">High</span><div class="number">${high}</div></div><div class="card"><span class="muted">Не подтверждено</span><div class="number">${unack}</div></div>`;initProblemFilters();applyProblemFilters()
  }catch(e){toast(e.message)}
}