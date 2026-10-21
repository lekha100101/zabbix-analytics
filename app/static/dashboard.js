function openSiteFromOverview(key){
  document.querySelectorAll('.nav,.tab').forEach(x=>x.classList.remove('active'));
  const nav=document.querySelector('.nav[data-tab="sites"]');if(nav)nav.classList.add('active');
  const tab=document.querySelector('#sites');if(tab)tab.classList.add('active');
  Promise.resolve(loadSites()).then(()=>{const q=document.querySelector('#siteSearch');if(q){q.value=key;if(typeof applySiteFilters==='function')applySiteFilters()}setTimeout(()=>document.querySelector('.site-row')?.scrollIntoView({behavior:'smooth',block:'center'}),80)});
}
function topProblem(x){return (x.top_problems||x.problems||[])[0]||null}
async function loadDashboard(){
  try{
    const d=await api('/api/v1/dashboard');window._dashboardData=d;
    const hostBad=d.hosts.unavailable>0,objBad=d.objects.with_unavailable_hosts>0,wanBad=d.internet.unavailable>0;
    document.querySelector('#overviewCards').innerHTML=`
      <div class="metric ${objBad?'metric-warn':'metric-ok'}"><span>Объекты</span><strong>${d.objects.total}</strong><small>${d.objects.healthy} без проблем · ${d.objects.with_unavailable_hosts} с недоступностью</small></div>
      <div class="metric ${hostBad?'metric-bad':'metric-ok'}"><span>Доступность хостов</span><strong>${d.hosts.availability_percent}%</strong><small>${d.hosts.available} из ${d.hosts.total} доступны</small></div>
      <div class="metric ${hostBad?'metric-bad':'metric-ok'}"><span>Недоступные хосты</span><strong>${d.hosts.unavailable}</strong><small>${d.hosts.affected} имеют активные проблемы</small></div>
      <div class="metric ${wanBad?'metric-bad':'metric-ok'}" onclick="document.querySelector('.nav[data-tab=internet]').click()" style="cursor:pointer"><span>Недоступный интернет</span><strong>${d.internet.unavailable}</strong><small>из ${d.internet.total} интернет-каналов</small></div>
      <div class="metric ${d.objects.critical?'metric-warn':'metric-ok'}"><span>Risk ≥ 70</span><strong>${d.objects.critical}</strong><small>объектов требуют анализа</small></div>`;
    document.querySelector('#overviewObjects').innerHTML=(d.important_objects||[]).map(x=>{const p=topProblem(x);return `<tr class="dashboard-object-row" onclick="openSiteFromOverview('${esc(x.site_key)}')"><td><b>${esc(x.site_key)}</b><small class="table-sub">${esc(x.zabbix_group_name||'')}</small></td><td><span class="risk risk-${x.risk_score>=70?'high':x.risk_score>=40?'mid':'low'}">${x.risk_score}</span></td><td><b>${x.active_problems}</b></td><td>${x.unavailable_hosts}/${x.hosts_total}</td><td>${p?'<b>'+esc(p.name)+'</b><small class="table-sub">Score '+p.impact_score+' · '+esc((p.hosts||[]).map(h=>h.name||h.host).join(', '))+'</small>':'—'}</td></tr>`}).join('')||'<tr><td colspan="5" class="empty">Проблемных объектов нет</td></tr>';
  }catch(e){toast(e.message)}
}
async function loadInternet(){
  try{
    const d=await api('/api/v1/internet/status');
    document.querySelector('#internetCards').innerHTML=`<div class="metric"><span>Контролируется</span><strong>${d.total}</strong><small>маршрутизаторов</small></div><div class="metric ${d.unavailable?'metric-bad':'metric-ok'}"><span>Недоступно</span><strong>${d.unavailable}</strong><small>${d.available} доступны</small></div><div class="metric ${d.unavailable?'metric-warn':'metric-ok'}"><span>Доступность</span><strong>${d.availability_percent}%</strong><small>по выбранным хостам</small></div>`;
    document.querySelector('#internetBody').innerHTML=(d.items||[]).map(x=>`<tr><td><b>${esc(x.name)}</b><small class="table-sub">${esc(x.host)}</small></td><td>${esc(x.problem)}</td><td><span class="risk risk-${x.score>=70?'high':x.score>=40?'mid':'low'}">${x.score}</span></td><td>${age(x.started_at)}</td></tr>`).join('')||'<tr><td colspan="4" class="empty">Недоступных маршрутизаторов нет</td></tr>';
    if(!document.querySelector('#internetRulePanel').hidden)loadInternetRules();
  }catch(e){toast(e.message)}
}
function toggleInternetRules(){const p=document.querySelector('#internetRulePanel');p.hidden=!p.hidden;if(!p.hidden)loadInternetRules()}
async function loadInternetRules(){try{const d=await api('/api/v1/internet/rules');document.querySelector('#internetRules').innerHTML=(d.items||[]).map(x=>`<div class="corr-rule"><div><b>${esc(x.name)}</b><small>${x.rule_type==='host_tag'?'HOST TAG: '+esc(x.key)+'='+esc(x.value):'HOST MASK: '+esc(x.value)}</small></div><button class="danger" onclick="deleteInternetRule(${x.id})">Удалить</button></div>`).join('')||'<div class="empty">Правил нет. По умолчанию используется hardware=gateway</div>'}catch(e){toast(e.message)}}
async function addInternetRule(){const type=prompt('Тип правила: tag или mask','tag');if(type===null)return;const isTag=type.toLowerCase().startsWith('t');let key=null,value;if(isTag){key=prompt('Tag key','hardware');if(key===null)return;value=prompt('Tag value','gateway')}else value=prompt('Маска имени хоста, например FGT-*','FGT-*');if(!value)return;const name=prompt('Название правила',isTag?key+'='+value:value);if(!name)return;try{await api('/api/v1/internet/rules',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,rule_type:isTag?'host_tag':'host_mask',key,value})});toast('Правило добавлено');loadInternetRules();loadInternet()}catch(e){toast(e.message)}}
async function deleteInternetRule(id){if(!confirm('Удалить правило?'))return;try{await api('/api/v1/internet/rules/'+id,{method:'DELETE'});loadInternetRules();loadInternet()}catch(e){toast(e.message)}}

loadDashboard();
