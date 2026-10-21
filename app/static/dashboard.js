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
    const d=await api('/api/v1/dashboard');window._dashboardData=d;const items=d.internet_down_objects||[];
    document.querySelector('#internetCards').innerHTML=`<div class="metric ${items.length?'metric-bad':'metric-ok'}"><span>Недоступно</span><strong>${items.length}</strong><small>объектов</small></div><div class="metric"><span>Всего каналов</span><strong>${d.internet.total}</strong><small>${d.internet.available} доступны</small></div>`;
    document.querySelector('#internetBody').innerHTML=items.map(x=>{const gw=(x.gateway_hosts||[]).map(h=>h.name||h.host).join(', ')||'—';const p=(x.problems||[]).find(p=>p.wan_unavailable||p.availability)||topProblem(x);return `<tr class="dashboard-object-row" onclick="openSiteFromOverview('${esc(x.site_key)}')"><td><b>${esc(x.site_key)}</b><small class="table-sub">${esc(x.zabbix_group_name||'')}</small></td><td>${esc(gw)}</td><td><span class="risk risk-${x.risk_score>=70?'high':x.risk_score>=40?'mid':'low'}">${x.risk_score}</span></td><td>${p?esc(p.name):esc(x.probable_cause||'—')}</td><td><span class="status bad"><i></i>Недоступен</span></td></tr>`}).join('')||'<tr><td colspan="5" class="empty">Объектов с недоступным интернетом нет</td></tr>';
  }catch(e){toast(e.message)}
}
loadDashboard();
