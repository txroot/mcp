import pytest

from sofia_ui import upgrade_control_center_html


BASE = """
<style>
.meta{margin:16px 0 14px;display:grid;gap:8px}
@media(max-width:620px){.shell{padding:0 15px 32px}
</style>
<p><strong>Online</strong> means registered services are running and ready. <strong>Degraded</strong> means the MCP is reachable but a dependency or tunnel still needs attention.</p>
<script>
const TOKEN='test';
function notify(){}
function refresh(){}
function card(i){const ms=i.memory_stats?`x`:'';return `<div class=\"card\"><div class=\"cardhead\">head</div><div class=\"meta\"><div class=\"row\"><div class=\"key\">Services</div></div></div><div class=\"actions\"><button class=\"btn\" onclick=\"act('${i.id}','start')\">Start</button><button class=\"btn\" onclick=\"act('${i.id}','restart')\">Restart</button><button class=\"btn danger\" onclick=\"act('${i.id}','stop')\">Stop</button></div></div>`}
async function act(id,action){if(action==='stop'&&!confirm('Stop '+id+'?'))return;notify(`${action} ${id}…`);try{const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-MCP-Control-Token':TOKEN},body:JSON.stringify({id,action})});const d=await r.json();notify(d.message||`${action} completed`,!d.ok);setTimeout(()=>refresh(false),900)}catch(e){notify('Action failed: '+e,true)}}
</script>
"""


def test_upgrade_adds_health_and_gateway_only_lifecycle():
    html = upgrade_control_center_html(BASE)

    assert "function healthCell" in html
    assert "function healthGrid" in html
    assert "healthCell('Process'" in html
    assert "healthCell('Provider'" in html
    assert "healthCell('Source'" in html
    assert "healthCell('Gateway'" in html
    assert "${healthGrid(i)}" in html
    assert "function lifeButton" in html
    assert "/api/lifecycle/prepare" in html
    assert "/api/lifecycle/execute" in html
    assert "Type CONFIRMO" in html
    assert "fetch('/api/action'" not in html
    assert "Gateway-only" in html
    assert ".btn:disabled" in html


def test_upgrade_is_fail_closed_when_legacy_html_shape_changes():
    with pytest.raises(ValueError, match="anchor not found"):
        upgrade_control_center_html("<html>unexpected</html>")
