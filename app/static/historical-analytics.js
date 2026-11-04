function fmtDays(v){return v===null||v===undefined?'—':v===0?'Уже':v+' д'}
async function loadReliability(){
 const info=$('#reliabilityInfo'),body=$('#reliabilityBody');info.textContent='Загрузка истории Zabbix…';
 try{const d=await api('/api/v1/analytics/reliability?days='+$('#reliabilityDays').value);
 info.textContent=d.note+(d.truncated?' ⚠ Достигнут лимит событий; статистика неполная.':'');
 body.innerHTML=(d.items||[]).map(x=>'<tr><td><b>'+esc(x.site_key)+'</b></td><td>'+x.hosts+'</td><td>'+x.incidents+'</td><td>'+x.event_minutes+' мин</td><td>'+(x.mttr_minutes===null?'—':x.mttr_minutes+' мин')+'</td><td>'+(x.last_incident?new Date(x.last_incident).toLocaleString('ru-RU'):'—')+'</td></tr>').join('')||'<tr><td colspan="6" class="empty">Нет данных</td></tr>';
 }catch(e){info.textContent='Ошибка: '+e.message;toast(e.message)}
}
async function loadCapacity(){
 const info=$('#capacityInfo'),body=$('#capacityBody');info.textContent='Загрузка трендов Zabbix (может занять время)…';
 try{const d=await api('/api/v1/analytics/capacity?days='+$('#capacityDays').value);info.textContent=d.note+' Найдено файловых систем: '+d.count;
 body.innerHTML=(d.items||[]).map(x=>'<tr><td><b>'+esc(x.site_key)+'</b><small class="table-sub">'+esc(x.hostid)+'</small></td><td>'+esc(x.filesystem)+'</td><td>'+x.used_percent+'%</td><td>'+x.used_tb+' / '+x.total_tb+' ТБ</td><td>'+(x.growth_gb_day===null?'—':x.growth_gb_day)+'</td><td>'+fmtDays(x.days_to_85)+'</td><td>'+fmtDays(x.days_to_95)+'</td></tr>').join('')||'<tr><td colspan="7" class="empty">Нет файловых систем с подходящими метриками</td></tr>';
 }catch(e){info.textContent='Ошибка: '+e.message;toast(e.message)}
}
