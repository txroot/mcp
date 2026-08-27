# Sofia Control Center

Interface local de observabilidade e operação assistida dos providers da Sofia OS.

> Estado desta branch: fundação de migração. O runtime legado ainda existe, mas a autoridade futura passa para o Sofia OS Gateway. O Control Center não deve tornar-se um caminho alternativo de execução.

## Princípio de arquitetura

```text
Sofia Control Center
        ↓
Sofia OS Gateway
        ↓
Capability / Contract
        ↓
Provider
        ↓
Sistema externo
```

O Control Center apresenta estado, logs, capabilities e ações disponíveis. A decisão de executar uma ação material deve ser validada pelo Gateway, incluindo contrato aplicável, nível de enforcement, approval quando necessário, preflight, trace e postflight.

## Provider contract

A fundação nova está em `sofia_provider.py` e define:

- `ProviderManifest`;
- `Capability`;
- níveis de enforcement `FULL`, `CONTROLLED`, `ADVISORY` e `UNSUPPORTED`;
- health separado em `process_health`, `provider_health`, `source_health` e `gateway_health`;
- bloqueio estrutural de `direct_external_exposure=true`;
- obrigatoriedade de `gateway_required=true`;
- declaração explícita de riscos e necessidade de approval por capability.

Existe um exemplo em `providers/example.provider.json` e testes em `tests/test_sofia_provider.py`.

## Função atual do Control Center legado

O serviço corre apenas em `127.0.0.1:18100` e reúne numa única UI:

- MCPs geridos;
- serviços `systemd --user` associados;
- estado `online` / `degraded` / `offline`;
- health/ready da camada local e dependências específicas;
- perfis `tunnel-client`;
- Start / Stop / Restart;
- logs;
- descoberta dinâmica das MCP tools realmente expostas pelo serviço;
- ligação à Admin UI técnica dos tunnels quando existe.

Estas capacidades serão migradas progressivamente para o modelo provider + Gateway. Durante a migração, nenhuma nova capability privilegiada deve ser adicionada diretamente ao Control Center legado.

## MCPs conhecidos no host legado

| MCP | MCP local | Tunnel/Admin | Estado esperado quando completo |
|---|---|---|---|
| Host Tools | `127.0.0.1:8766/mcp` | `18082` | Online |
| Google Tasks | stdio via tunnel | `18102` | Online |
| Memory | `127.0.0.1:8765/mcp` | `18103` | Online |
| Google Analytics | `127.0.0.1:8767/mcp` | `18104` | Online |
| PrestaShop | `127.0.0.1:8769/mcp` | `18105` | Online |

As portas são configuração do host, não uma exigência do protocolo.

## Segurança

### Baseline atual

- bind apenas em loopback;
- token de controlo em `~/.config/mcp-control-center/token`, nunca no Git;
- ações limitadas a units explicitamente registadas;
- logs passam por redaction básica de tokens/authorization;
- não expor o Control Center diretamente à Internet.

### Requisitos da migração

Antes de produção, o desenho novo deve ainda:

- remover bearer reutilizável embebido no HTML;
- autenticar a sessão/UI de forma adequada;
- validar `Host` e `Origin`;
- aplicar proteção CSRF às ações de mutação;
- encaminhar ações materiais pelo Sofia OS Gateway;
- distinguir sempre process, provider, source e gateway health;
- preservar audit trace e postflight.

## Instalação legado

```bash
./scripts/install_local.sh
systemctl --user status mcp-control-center.service
```

Abrir localmente:

```text
http://127.0.0.1:18100
```

## Adicionar um provider novo

O alvo é deixar de editar diretamente um registry hardcoded. Um provider deve passar a declarar um manifest validável com:

1. ID e versão;
2. capabilities;
3. nível de enforcement por capability;
4. riscos;
5. necessidade de approval;
6. health de processo, provider, fonte e Gateway;
7. `gateway_required=true`;
8. `direct_external_exposure=false`.

O provider só deverá ser integrado no runtime depois de passar validação, testes e compatibilidade com o Capability Gateway.

## Migração

O token local e quaisquer credenciais das dependências não são migrados pelo Git; devem ser recriados ou restaurados pelo canal seguro adequado.

A sequência prevista é:

1. contrato standard de provider;
2. loader/validator e testes;
3. migração do inventário hardcoded para manifests;
4. separação completa dos quatro níveis de health;
5. adaptação das ações ao Sofia OS Gateway;
6. hardening da UI/autenticação;
7. integração do terminal persistente como `provider-terminal-privileged`;
8. testes end-to-end antes de merge/deploy.
