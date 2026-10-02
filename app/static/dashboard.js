function openSiteFromOverview(key){
  document.querySelectorAll('.nav,.tab').forEach(x=>x.classList.remove('active'));
  const nav=document.querySelector('.nav[data-tab="sites"]');
  if(nav)nav.classList.add('active');
  const tab=document.querySelector('#sites');if(tab)tab.classList.add('active');
  Promise.resolve(loadSites()).then(()=>{
    const q=document.querySelector('#siteSearch');
    if(q){q.value=key;if(typeof applySiteFilters==='function')applySiteFilters()}
    setTimeout(()=>document.querySelector('.site-row')?.scrollIntoView({behavior:'smooth',block:'center'}),80);
  });
}
async function loadDashboard(){
  try{
    const d=await api('/api/v1/dashboard');
    const hostBad=d.hosts.unavailable>0,wanBad=d.internet.unavailable>0,objBad=d.objects.with_unavailable_hosts>0;
    document.querySelector('#overviewCards').innerHTML=`
      <div class="metric ${objBad?'metric-warn':'metric-ok'}"><span>Объекты</span><strong>${d.objects.total}</strong><small>${d.objects.healthy} без проблем · ${d.objects.with_unavailable_hosts} с недоступностью</small></div>
      <div class="metric ${hostBad?'metric-bad':'metric-ok'}"><span>Доступность хостов</span><strong>${d.hosts.availability_percent}%</strong><small>${d.hosts.available} из ${d.hosts.total} доступны</small></div>
      <div class="metric ${hostBad?'metric-bad':'metric-ok'}"><span>Недоступные хосты</span><strong>${d.hosts.unavailable}</strong><small>${d.hosts.affected} имеют активные проблемы</small></div>
      <div class="metric ${wanBad?'metric-bad':'metric-ok'}"><span>Интернет-каналы</span><strong>${d.internet.available}/${d.internet.total}</strong><small>${wanBad?d.internet.unavailable+' недоступно':'Все gateway доступны'}</small></div>
      <div class="metric ${d.objects.critical?'metric-warn':'metric-ok'}"><span>Risk ≥ 70</span><strong>${d.objects.critical}</strong><small>объектов требуют анализа</small></div>`;
    document.querySelector('#overviewObjects').innerHTML=(d.important_objects||[]).map(x=>`<tr class="dashboard-object-row" onclick="openSiteFromOverview('${esc(x.site_key)}')"><td><b>${esc(x.site_key)}</b><small class="table-sub">${esc(x.zabbix_group_name||'')}</small></td><td>${x.internet_status==='down'?'<span class="status bad"><i></i>Интернет</span>':x.unavailable_hosts?'<span class="status bad"><i></i>Недоступность</span>':x.active_problems?'<span class="site-warning">Проблемы</span>':'<span class="status ok"><i></i>Норма</span>'}</td><td>${x.affected_hosts}/${x.hosts_total}</td><td>${x.unavailable_hosts}</td><td>${esc(x.probable_cause||'Активные проблемы')}</td></tr>`).join('')||'<tr><td colspan="5" class="empty">Проблемных объектов нет</td></tr>';
    document.querySelector('#internetList').innerHTML=(d.internet_channels||[]).map(x=>`<div class="status-row dashboard-channel" onclick="openSiteFromOverview('${esc(x.site_key)}')"><div><b>${esc(x.site_key)}</b><small>${x.gateways} gateway${x.cause?' · '+esc(x.cause):''}</small></div>${statusBadge(x.available)}</div>`).join('')||'<div class="empty">В SITE-объектах пока не обнаружены gateway-хосты</div>';
  }catch(e){toast(e.message)}
}
loadDashboard();