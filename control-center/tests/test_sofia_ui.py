import pytest

from sofia_ui import upgrade_control_center_html


BASE = """
<style>
.meta{margin:16px 0 14px;display:grid;gap:8px}
@media(max-width:620px){.shell{padding:0 15px 32px}
</style>
<p><strong>Online</strong> means registered services are running and ready. <strong>Degraded</strong> means the MCP is reachable but a dependency or tunnel still needs attention.</p>
<script>
function card(i){const ms=i.memory_stats?`x`:'';return `<div class=\"card\"><div class=\"cardhead\">head</div><div class=\"meta\"><div class=\"row\"><div class=\"key\">Services</div></div></div>`}
</script>
"""


def test_upgrade_adds_four_health_cells_and_preserves_card_function():
    html = upgrade_control_center_html(BASE)

    assert "function healthCell" in html
    assert "function healthGrid" in html
    assert "healthCell('Process'" in html
    assert "healthCell('Provider'" in html
    assert "healthCell('Source'" in html
    assert "healthCell('Gateway'" in html
    assert "${healthGrid(i)}" in html
    assert "function card(i)" in html
    assert "Unknown means evidence is not yet wired" in html


def test_upgrade_is_fail_closed_when_legacy_html_shape_changes():
    with pytest.raises(ValueError, match="anchor not found"):
        upgrade_control_center_html("<html>unexpected</html>")
