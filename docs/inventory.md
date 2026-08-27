# MCP inventory

Inventário do host de desenvolvimento atualizado em 2026-08-27.

| MCP | Código no `txroot/mcp` | Serviço local | Tunnel |
|---|---|---|---|
| Host Tools | Migração para repo pendente | `host-tools-mcp-v2.service` | `host-tools-tunnel-v2.service` |
| Google Tasks | Migração para repo pendente | através do tunnel/stdio | `mcp-google-tasks-tunnel.service` |
| Memory | Migração para repo pendente | `mcp-memory.service` | `mcp-memory-tunnel.service` |
| Google Analytics | Migração para repo pendente | `mcp-google-analytics.service` | `mcp-google-analytics-tunnel.service` |
| PrestaShop | **Sim** | `mcp-prestashop.service` | `mcp-prestashop-tunnel.service` (`prestashop`) |
| MCP Control Center | **Sim** | `mcp-control-center.service` | não aplicável |
| Interactive Terminal | **Sim** | `mcp-terminal.service` | `mcp-terminal-tunnel.service` (`terminal`) |

## Regra

Nenhum MCP novo deve ficar apenas “detetado”. Para ser considerado integrado no host deve ter:

- estado no Control Center;
- serviço persistente quando aplicável;
- logs;
- Start/Stop/Restart;
- health/ready relevante;
- tunnel quando necessário para ChatGPT;
- README de instalação/reinstalação;
- segredos fora do Git.
