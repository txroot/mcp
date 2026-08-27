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
- ligação à Admin UI técnica dos tunnels quando existe;
- consola **Terminal** integrada para sessões PTY partilhadas do Interactive Terminal MCP;
- política de espera por intervenção configurável globalmente e por sessão (5 min, 15 min, 30 min, 1 h, 4 h ou Unlimited), sem fechar a PTY quando expira.

A separação é de **serviços**, não de aplicações de administração: cada MCP continua independente, mas a operação diária é centralizada aqui.

## MCPs conhecidos no host atual

| MCP | MCP local | Tunnel/Admin | Estado esperado quando completo |
|---|---|---|---|
| Host Tools | `127.0.0.1:8766/mcp` | `18082` | Online |
| Google Tasks | stdio via tunnel | `18102` | Online |
| Memory | `127.0.0.1:8765/mcp` | `18103` | Online |
| Google Analytics | `127.0.0.1:8767/mcp` | `18104` | Online |
| PrestaShop | `127.0.0.1:8769/mcp` | `18105` | Online |
| Interactive Terminal | `127.0.0.1:8770/mcp` | local PTY API `18107`; tunnel/admin `18108` | Online |

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
## Interactive Terminal identification and timestamps

The Terminal view shows each session's four-character `terminal_code`, live local time, creation time and last activity. User and AI interventions are annotated visually with timestamps and distinct colored markers (`● USER` and `✦ AI`) using side-band metadata; typed content is not stored in those events. The long `term_<hex>` ID remains available for diagnostics. The top bar keeps the sidebar control and `Interactive Terminal` identity on the left and the return to MCP Control Center on the right. Terminal creation, refresh and wait settings live in the terminal-list sidebar. The sidebar can be hidden/shown on desktop (preference remembered locally) and becomes an off-canvas drawer on mobile. The xterm is refitted after layout changes. Keystroke echo is accelerated through immediate short read bursts after writes, without browser-side local echo, so sudo/password echo semantics remain controlled only by the PTY. The desktop sidebar width is mouse-resizable (280–600 px, 340 px default), persisted locally, and double-clicking the divider resets it. A compact search filters terminal cards by name, short code, technical ID, cwd, or state. **Clear closed terminals** removes only exited sessions after confirmation and never touches running sessions. The **Terminal settings** dialog also configures automatic cleanup of closed sessions (default 24 h; Off/6 h/12 h/24 h/3 d/7 d/30 d). Automatic cleanup starts counting from `closed_at` and never deletes a running PTY.
