# MCP Control Center

Interface local autoritativa para inventário, estado e operação dos MCPs instalados no computador.

## Função

O Control Center corre apenas em `127.0.0.1:18100` e reúne numa única UI:

- MCPs geridos;
- serviços `systemd --user` associados;
- estado `online` / `degraded` / `offline`;
- health/ready da camada local e dependências específicas;
- perfis `tunnel-client`;
- Start / Stop / Restart;
- logs;
- botão **Info** com descoberta dinâmica das MCP tools realmente expostas pelo serviço;
- ligação à Admin UI técnica dos tunnels quando existe.

A separação é de **serviços**, não de aplicações de administração: cada MCP continua independente, mas a operação diária é centralizada aqui.

## MCPs conhecidos no host atual

| MCP | MCP local | Tunnel/Admin | Estado esperado quando completo |
|---|---|---|---|
| Host Tools | `127.0.0.1:8766/mcp` | `18082` | Online |
| Google Tasks | stdio via tunnel | `18102` | Online |
| Memory | `127.0.0.1:8765/mcp` | `18103` | Online |
| Google Analytics | `127.0.0.1:8767/mcp` | `18104` | Online |
| PrestaShop | `127.0.0.1:8769/mcp` | `18105` | Online |

As portas são configuração do host, não uma exigência do protocolo.

## Segurança

- bind apenas em loopback;
- token de controlo em `~/.config/mcp-control-center/token`, nunca no Git;
- ações limitadas a units explicitamente registadas;
- logs passam por redaction básica de tokens/authorization;
- não expor o Control Center diretamente à Internet.

## Instalação

```bash
./scripts/install_local.sh
systemctl --user status mcp-control-center.service
```

Abrir localmente:

```text
http://127.0.0.1:18100
```

## Adicionar um MCP

1. instalar e validar primeiro o MCP local;
2. criar serviço e, se necessário, tunnel;
3. adicionar uma entrada a `MCP_REGISTRY`;
4. garantir que todas as units ficam em `SAFE_UNITS` através do registry;
5. configurar `tools_probe` para o botão **Info** conseguir descobrir as tools reais;
6. acrescentar um probe específico se a disponibilidade da fonte for diferente do simples health do tunnel;
7. verificar que uma dependência em falta produz `degraded`, não um falso `online`;
8. atualizar este README/inventário.

## Migração

O código do Control Center está neste diretório. O token local e quaisquer credenciais das dependências não são migrados pelo Git; devem ser recriados ou restaurados pelo canal seguro adequado.
