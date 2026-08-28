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
- health contratado em `process_health`, `provider_health`, `source_health` e `gateway_health`;
- health materializado separadamente na API através de `health_layers`;
- grelha visual Process / Provider / Source / Gateway no dashboard;
- estado Gateway `unknown` enquanto não existir evidência real, sem o promover artificialmente a healthy;
- bloqueio de `direct_external_exposure=true`;
- obrigatoriedade de `gateway_required=true`;
- loader de manifests em `sofia_registry.py`;
- entrypoint transitório `sofia_server.py`;
- PrestaShop como primeiro provider real migrado para manifest;
- Google Analytics como segundo provider real migrado para manifest;
- `source_probe` simbólico no runtime contract, sem comandos ou callables vindos do manifest;
- allowlist de source-health no servidor e adapter genérico em `sofia_source_health.py`;
- fallback para o registry legado nos providers ainda não migrados;
- CI GitHub Actions com compilação, validação de manifests, testes e `bash -n`;
- testes unitários do contrato, registry, source-health, quatro camadas de health e UI.

### Ainda não concluído

- Start / Stop / Restart ainda usam a implementação legada e **não estão ainda encaminhados pelo Sofia OS Gateway**;
- bearer reutilizável ainda existe no HTML legado;
- Host/Origin/CSRF ainda não foram endurecidos;
- Host Tools, Google Tasks e Memory ainda precisam de manifest próprio;
- Gateway health ainda não tem probe/evidência real e aparece corretamente como `unknown` nos providers gateway-first;
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
- `source_probe` simbólico;
- configuração de descoberta de tools.

Os manifests não contêm secrets. Caminhos portáveis podem usar `${HOME}`.

`source_probe` não contém código. Aceita apenas um identificador simbólico lowercase e esse identificador tem de existir na allowlist do servidor. Um manifest não pode introduzir shell, um comando ou um callable arbitrário através deste campo.

## PrestaShop — provider piloto

`providers/prestashop.provider.json` foi o primeiro manifest operacional real.

Declara, entre outras, as capabilities:

- `prestashop.health`;
- `prestashop.orders.read`;
- `prestashop.catalog.read`;
- `prestashop.catalog.audit`;
- `prestashop.stock.read`;
- `prestashop.abandoned_carts.read`;
- `prestashop.duplicates.audit`.

Todas são atualmente read-only. As capabilities que podem tocar dados de clientes declaram o risco `customer_data`.

O manifest declara `source_probe: prestashop`; a implementação executável continua na allowlist do servidor.

## Google Analytics — segundo provider

`providers/google-analytics.provider.json` prova que o padrão é repetível num segundo serviço read-only.

Declara:

- `google_analytics.health`;
- `google_analytics.report.read`;
- `google_analytics.metadata.read`.

A configuração runtime — serviços, profile, MCP local, health endpoint, Admin UI e tool discovery — deixa de depender da entrada hardcoded no caminho novo. O manifest declara `source_probe: google_analytics`.

O source-health continua a usar a verificação GA4 read-only existente. A seleção do probe passa agora pelo registry/manifest; o código executável é resolvido apenas pela allowlist do `sofia_server.py`.

## Source-health adapter

`sofia_source_health.py` aplica source-health aos itens do status payload:

1. lê `source_probe` do registry manifest-driven;
2. resolve o nome numa allowlist fornecida pelo servidor;
3. reutiliza um resultado legado já existente para evitar chamadas duplicadas durante a fase de migração;
4. quando não existe resultado, executa apenas o probe allowlisted;
5. um probe desconhecido falha de forma segura;
6. publica `source_health=healthy|unhealthy`;
7. degrada o estado global quando a fonte está indisponível ou o tunnel necessário não está configurado.

Este adapter permite remover posteriormente as exceções `if ident == ...` do servidor legado sem alterar o contrato dos manifests.

## Quatro camadas de health

`sofia_health.py` enriquece cada item da API com:

```json
{
  "health_layers": {
    "process": {"state": "healthy", "text": "...", "required": true},
    "provider": {"state": "healthy", "text": "...", "required": true},
    "source": {"state": "healthy", "text": "...", "required": true},
    "gateway": {"state": "unknown", "text": "...", "required": true}
  }
}
```

Regras atuais:

- **Process** deriva do estado dos serviços registados;
- **Provider** deriva do live/ready probe local;
- **Source** deriva do `source_access` produzido pelo probe allowlisted;
- **Gateway** só fica healthy/unhealthy quando existir `gateway_access` real; enquanto essa evidência não estiver ligada, providers gateway-first aparecem como `unknown`;
- providers legados também recebem as quatro chaves para uniformidade, mas camadas ainda não contratadas ficam `unknown` e `required=false`;
- o `state` agregado legado é preservado durante a migração para evitar alterações de comportamento no summary e nas automações existentes.

A API acrescenta ainda contagens por layer em `summary.health_layers`.

`sofia_ui.py` injeta no HTML legado uma grelha compacta de quatro células por provider. A transformação é fail-closed: se os anchors esperados do HTML legado mudarem, a inicialização falha em vez de apresentar uma UI parcialmente atualizada.

## Loader de registry

`sofia_registry.py`:

1. copia o registry legado sem o modificar;
2. lê `providers/*.provider.json`;
3. valida cada manifest;
4. falha de forma segura em manifests inválidos ou IDs runtime duplicados;
5. expande `${HOME}` apenas em configuração runtime;
6. transporta `source_probe` para o runtime registry;
7. sobrepõe apenas os `registry_id` que têm runtime declarado;
8. mantém compatibilidade com providers ainda não migrados;
9. adiciona metadata `provider_manifest` ao item runtime para observabilidade.

## Entry point transitório

`sofia_server.py` importa o servidor legado e aplica o registry manifest-driven antes de iniciar o HTTP server.

Também instala a allowlist de source-health:

- `google_analytics` → probe GA4 read-only existente;
- `prestashop` → probe PrestaShop read-only existente.

Depois do payload legado, o entrypoint aplica source-health e as quatro camadas de health. A UI é enriquecida por `sofia_ui.py` sem alterar o `server.py` legado, preservando rollback simples.

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
| Google Analytics | `127.0.0.1:8767/mcp` | `18104` | **Manifest** |
| PrestaShop | `127.0.0.1:8769/mcp` | `18105` | **Manifest** |

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
- ligar gateway health a evidência real do Gateway;
- preservar audit trace e postflight;
- testar rollback para o entrypoint legado.

## CI

`.github/workflows/sofia-control-center-ci.yml` valida alterações relevantes com permissões `contents: read`:

- compilação dos módulos Python, incluindo health e UI;
- validação de todos os manifests;
- confirmação dos providers migrados;
- confirmação de `gateway_required=true` e `direct_external_exposure=false`;
- confirmação dos quatro campos do health contract;
- confirmação de source probes declarados;
- testes unitários;
- `bash -n` do instalador.

Não existe passo de deploy no workflow.

## Instalação candidata

O script desta branch instala `server.py`, `sofia_server.py`, os módulos de provider/registry/source-health/health/UI e os manifests, compila os ficheiros Python e atualiza o unit file.

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
9. runtime operacional quando for gerido pelo Control Center;
10. `source_probe` simbólico quando a disponibilidade da fonte exige verificação própria.

O provider só deve entrar no runtime depois de validação, testes e compatibilidade com o Capability Gateway.

## Sequência seguinte

1. ligar `gateway_health` a evidência real do Sofia OS Gateway;
2. migrar um terceiro provider simples para confirmar repetibilidade;
3. substituir Start / Stop / Restart por operações mediadas pelo Sofia OS Gateway;
4. hardening da UI/autenticação;
5. integrar `provider-terminal-privileged`;
6. testes end-to-end;
7. apenas depois preparar PR/merge/deploy.
