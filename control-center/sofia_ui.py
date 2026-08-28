from __future__ import annotations


_STYLE_ANCHOR = ".meta{margin:16px 0 14px;display:grid;gap:8px}"
_STYLE_REPLACEMENT = ".healthgrid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:7px;margin:14px 0 4px}.healthcell{border:1px solid var(--line);background:#0c1420;border-radius:9px;padding:8px 9px;min-width:0}.healthlabel{display:block;color:#6f829c;font-size:9px;text-transform:uppercase;letter-spacing:.075em;margin-bottom:4px}.healthstate{font-size:11px;font-weight:750}.healthstate.healthy{color:var(--green)}.healthstate.degraded{color:var(--amber)}.healthstate.unhealthy{color:var(--red)}.healthstate.unknown{color:#95a4b8}.healthtext{display:block;color:var(--muted);font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px}.btn:disabled{opacity:.38;cursor:not-allowed;filter:saturate(.35)}.domaincomponents{display:grid;gap:7px;margin-top:14px}.domaincomponent{border:1px solid var(--line);background:#0c1420;border-radius:9px;padding:8px 10px}.domaincomponent b{font-size:11px}.domaincomponent small{display:block;color:var(--muted);margin-top:3px}.meta{margin:16px 0 14px;display:grid;gap:8px}"

_CARD_ANCHOR = "function card(i){const ms=i.memory_stats?"
_CARD_REPLACEMENT = "function healthCell(label,layer){const x=layer||{state:'unknown',text:'No evidence'};return `<div class=\"healthcell\" title=\"${esc(x.text||'')}\"><span class=\"healthlabel\">${label}</span><span class=\"healthstate ${esc(x.state||'unknown')}\">${esc(x.state||'unknown')}</span><span class=\"healthtext\">${esc(x.text||'')}</span></div>`}\nfunction healthGrid(i){const h=i.health_layers||{};return `<div class=\"healthgrid\">${healthCell('Process',h.process)}${healthCell('Provider',h.provider)}${healthCell('Source',h.source)}${healthCell('Gateway',h.gateway)}</div>`}\nfunction lifeButton(i,action,label,extra=''){const l=i.lifecycle||{};const enabled=l[action]===true;const click=enabled?`onclick=\"act('${i.id}','${action}')\"`:'';const title=enabled?'Gateway-mediated; explicit CONFIRMO required':'Gateway lifecycle action unavailable';return `<button class=\"btn ${extra}\" ${click} ${enabled?'':'disabled'} title=\"${title}\">${label}</button>`}\nfunction domainComponent(c){const exposure=c.gateway_exposed?'Gateway exposed':'Gateway wiring pending';const status=c.status_tool?`status: ${esc(c.status_tool)}`:'status tool pending';return `<div class=\"domaincomponent\"><b>${esc(c.component_id)}</b><small>${esc(c.role)} · ${esc(c.kind)} · ${exposure}</small><small><code>${esc(c.target)}</code></small><small>${status}</small></div>`}\nfunction domainCard(d){return `<div class=\"card\"><div class=\"cardhead\"><div><div class=\"name\">${esc(d.name)}</div><div class=\"desc\">Canonical Sofia OS domain · lifecycle disabled during reconciliation</div></div><span class=\"pill degraded\">reconciled</span></div><div class=\"domaincomponents\">${(d.components||[]).map(domainComponent).join('')}</div></div>`}\nfunction renderGrid(payload){const domains=(payload.runtime_inventory&&payload.runtime_inventory.domains)||[];if(domains.length)return domains.map(domainCard).join('');return (payload.items||[]).map(card).join('')}\nfunction card(i){const ms=i.memory_stats?"

_META_ANCHOR = "</div><div class=\"meta\"><div class=\"row\"><div class=\"key\">Services</div>"
_META_REPLACEMENT = "</div>${healthGrid(i)}<div class=\"meta\"><div class=\"row\"><div class=\"key\">Services</div>"

_ACTIONS_ANCHOR = "<div class=\"actions\"><button class=\"btn\" onclick=\"act('${i.id}','start')\">Start</button><button class=\"btn\" onclick=\"act('${i.id}','restart')\">Restart</button><button class=\"btn danger\" onclick=\"act('${i.id}','stop')\">Stop</button>"
_ACTIONS_REPLACEMENT = "<div class=\"actions\">${lifeButton(i,'start','Start')}${lifeButton(i,'restart','Restart')}${lifeButton(i,'stop','Stop','danger')}"

_GRID_ANCHOR = "document.getElementById('grid').innerHTML=d.items.map(card).join('');"
_GRID_REPLACEMENT = "document.getElementById('grid').innerHTML=renderGrid(d);"

_ACT_ANCHOR = "async function act(id,action){if(action==='stop'&&!confirm('Stop '+id+'?'))return;notify(`${action} ${id}…`);try{const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-MCP-Control-Token':TOKEN},body:JSON.stringify({id,action})});const d=await r.json();notify(d.message||`${action} completed`,!d.ok);setTimeout(()=>refresh(false),900)}catch(e){notify('Action failed: '+e,true)}}"
_ACT_REPLACEMENT = """async function act(id,action){
  notify(`Preparing ${action} ${id} through Sofia OS Gateway…`);
  try{
    const pr=await fetch('/api/lifecycle/prepare',{method:'POST',headers:{'Content-Type':'application/json','X-MCP-Control-Token':TOKEN},body:JSON.stringify({id,action})});
    const prepared=await pr.json();
    if(!pr.ok||!prepared.ok){notify(prepared.message||'Gateway lifecycle preparation blocked',true);refresh(false);return}
    const confirmation=prompt(`${prepared.message||'Lifecycle prepared.'}\\n\\nType CONFIRMO to execute ${action} on ${id}:`);
    if(confirmation!=='CONFIRMO'){notify('Lifecycle cancelled before execution');return}
    notify(`Executing ${action} ${id} through Sofia OS Gateway…`);
    const er=await fetch('/api/lifecycle/execute',{method:'POST',headers:{'Content-Type':'application/json','X-MCP-Control-Token':TOKEN},body:JSON.stringify({approval_id:prepared.approval_id,confirmation})});
    const executed=await er.json();
    notify(executed.message||`${action} completed`,!er.ok||!executed.ok);
    setTimeout(()=>refresh(false),900)
  }catch(e){notify('Gateway lifecycle failed: '+e,true)}
}"""

_MEDIA_ANCHOR = "@media(max-width:620px){.shell{padding:0 15px 32px}"
_MEDIA_REPLACEMENT = "@media(max-width:760px){.healthgrid{grid-template-columns:1fr 1fr}}@media(max-width:620px){.shell{padding:0 15px 32px}"

_HELP_ANCHOR = "<p><strong>Online</strong> means registered services are running and ready. <strong>Degraded</strong> means the MCP is reachable but a dependency or tunnel still needs attention.</p>"
_HELP_REPLACEMENT = "<p><strong>Online</strong> means registered services are running and ready. <strong>Degraded</strong> means the MCP is reachable but a dependency or tunnel still needs attention.</p><p>The reconciled view groups Sofia OS by <strong>real domains</strong> and components instead of the obsolete one-MCP-per-card model. A domain marked <strong>reconciled</strong> reflects canonical topology; live per-component health is the next integration layer.</p><p>Start, Stop and Restart remain <strong>fail-closed</strong>. No reconciled domain has lifecycle enabled until the Gateway exposes a canonical provider inventory and matching allowlisted actions.</p>"


def upgrade_control_center_html(html: str) -> str:
    replacements = (
        (_STYLE_ANCHOR, _STYLE_REPLACEMENT),
        (_CARD_ANCHOR, _CARD_REPLACEMENT),
        (_META_ANCHOR, _META_REPLACEMENT),
        (_ACTIONS_ANCHOR, _ACTIONS_REPLACEMENT),
        (_GRID_ANCHOR, _GRID_REPLACEMENT),
        (_ACT_ANCHOR, _ACT_REPLACEMENT),
        (_MEDIA_ANCHOR, _MEDIA_REPLACEMENT),
        (_HELP_ANCHOR, _HELP_REPLACEMENT),
    )
    updated = html
    for anchor, replacement in replacements:
        if anchor not in updated:
            raise ValueError(f"Control Center HTML anchor not found: {anchor[:48]}")
        updated = updated.replace(anchor, replacement, 1)
    return updated
