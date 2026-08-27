# Sofia Control Center

Interface local de observabilidade e operação assistida dos providers da Sofia OS.

> Estado desta branch: migração gateway-first em desenvolvimento. O runtime legado continua disponível para compatibilidade, mas a autoridade alvo é o Sofia OS Gateway. O Control Center não deve tornar-se um caminho alternativo de execução.

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

## Estado da migração

### Concluído nesta branch

- contrato `ProviderManifest`;
- `RuntimeContract` para descrever integração operacional sem hardcode no `server.py`;
- níveis de enforcement `FULL`, `CONTROLLED`, `ADVISORY` e `UNSUPPORTED`;
- health separado em `process_health`, `provider_health`, `source_health` e `gateway_health`;
- bloqueio de `direct_external_exposure=true`;
- obrigatoriedade de `gateway_required=true`;
- loader de manifests em `sofia_registry.py`;
- entrypoint transitório `sofia_server.py`;
- PrestaShop como primeiro provider real migrado para manifest;
- fallback para o registry legado nos providers ainda não migrados;
- testes unitários do contrato e da migração de registry.

### Ainda não concluído

- Start / Stop / Restart ainda usam a implementação legada e **não estão ainda encaminhados pelo Sofia OS Gateway**;
- bearer reutilizável ainda existe no HTML legado;
- Host/Origin/CSRF ainda não foram endurecidos;
- os restantes providers ainda precisam de manifest próprio;
- o terminal persistente ainda não está integrado;
- esta branch ainda não foi instalada nem ativada em produção.

## Provider contract

A fundação está em `sofia_provider.py` e define:

- `ProviderManifest`;
- `Capability`;
- `RuntimeContract`;
- `HealthContract`;
- níveis de enforcement;
- riscos e necessidade de approval por capability;
- regras estruturais gateway-first.

Existe um exemplo abstrato em `providers/example.provider.json`.

Um provider gerido pelo Control Center pode acrescentar uma secção `runtime` com:

- `registry_id`;
- serviços `systemd`;
- profile/tunnel;
- endpoint MCP;
- health endpoint;
- Admin UI local;
- tipo de probe;
- configuração de descoberta de tools.

Os manifests não contêm secrets. Caminhos portáveis podem usar `${HOME}`.

## PrestaShop — provider piloto

`providers/prestashop.provider.json` é o primeiro manifest operacional real.

Declara, entre outras, as capabilities:

- `prestashop.health`;
- `prestashop.orders.read`;
- `prestashop.catalog.read`;
- `prestashop.catalog.audit`;
- `prestashop.stock.read`;
- `prestashop.abandoned_carts.read`;
- `prestashop.duplicates.audit`.

Todas são atualmente read-only. As capabilities que podem tocar dados de clientes declaram o risco `customer_data`.

No entrypoint novo, a configuração runtime do PrestaShop vem do manifest e substitui apenas a entrada `prestashop` do registry legado. As restantes entradas permanecem inalteradas até à respetiva migração.

## Loader de registry

`sofia_registry.py`:

1. copia o registry legado sem o modificar;
2. lê `providers/*.provider.json`;
3. valida cada manifest;
4. falha de forma segura em manifests inválidos ou IDs runtime duplicados;
5. expande `${HOME}` apenas em configuração runtime;
6. sobrepõe apenas os `registry_id` que têm runtime declarado;
7. mantém compatibilidade com providers ainda não migrados;
8. adiciona metadata `provider_manifest` ao item runtime para observabilidade.

## Entry point transitório

`sofia_server.py` importa o servidor legado e aplica o registry manifest-driven antes de iniciar o HTTP server.

Isto permite migrar provider a provider sem reescrever já o `server.py` monolítico e dá rollback simples: o `server.py` original permanece intacto nesta fase.

O unit file da branch aponta para `sofia_server.py`. Isso **não significa que esteja instalado em produção**; o ficheiro é apenas a definição candidata para testes/deploy posterior.

## Função atual do Control Center legado

O serviço corre apenas em `127.0.0.1:18100` e reúne numa única UI:

- providers/MCPs geridos;
- serviços `systemd --user` associados;
- estado `online` / `degraded` / `offline`;
- health/ready da camada local e dependências específicas;
- perfis `tunnel-client`;
- Start / Stop / Restart;
- logs;
- descoberta dinâmica das MCP tools;
- ligação à Admin UI técnica dos tunnels quando existe.

Estas capacidades serão migradas progressivamente para provider + Gateway. Durante a migração, nenhuma nova capability privilegiada deve ser adicionada diretamente ao Control Center legado.

## Providers conhecidos no host legado

| Provider | MCP local | Tunnel/Admin | Migração |
|---|---|---|---|
| Host Tools | `127.0.0.1:8766/mcp` | `18082` | Legado |
| Google Tasks | stdio via tunnel | `18102` | Legado |
| Memory | `127.0.0.1:8765/mcp` | `18103` | Legado |
| Google Analytics | `127.0.0.1:8767/mcp` | `18104` | Legado |
| PrestaShop | `127.0.0.1:8769/mcp` | `18105` | **Manifest piloto** |

As portas são configuração do host, não uma exigência do protocolo.

## Segurança

### Baseline atual

- bind apenas em loopback;
- token de controlo em `~/.config/mcp-control-center/token`, nunca no Git;
- ações limitadas a units registadas;
- logs passam por redaction básica de tokens/authorization;
- não expor o Control Center diretamente à Internet.

### Requisitos antes de produção

- remover bearer reutilizável embebido no HTML;
- autenticar a sessão/UI de forma adequada;
- validar `Host` e `Origin`;
- aplicar proteção CSRF às ações de mutação;
- encaminhar ações materiais pelo Sofia OS Gateway;
- distinguir process, provider, source e gateway health com evidência própria;
- preservar audit trace e postflight;
- testar rollback para o entrypoint legado.

## Instalação candidata

O script desta branch instala `server.py`, `sofia_server.py`, os módulos de provider/registry e os manifests, compila os ficheiros Python e atualiza o unit file.

```bash
./scripts/install_local.sh
systemctl --user status mcp-control-center.service
```

**Não executar em produção sem uma etapa explícita de validação e aprovação.**

## Adicionar um provider novo

O alvo é deixar de editar diretamente o registry hardcoded. Um provider deve declarar um manifest validável com:

1. ID e versão;
2. capabilities;
3. nível de enforcement por capability;
4. riscos;
5. necessidade de approval;
6. health de processo, provider, fonte e Gateway;
7. `gateway_required=true`;
8. `direct_external_exposure=false`;
9. runtime operacional quando for gerido pelo Control Center.

O provider só deve entrar no runtime depois de validação, testes e compatibilidade com o Capability Gateway.

## Sequência seguinte

1. validar testes do manifest + registry num runner;
2. migrar mais um provider simples para provar repetibilidade;
3. expor os quatro níveis de health na API/UI;
4. substituir Start / Stop / Restart por operações mediadas pelo Sofia OS Gateway;
5. hardening da UI/autenticação;
6. integrar `provider-terminal-privileged`;
7. testes end-to-end;
8. apenas depois preparar PR/merge/deploy.
