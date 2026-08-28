# Sofia Control Center

Interface local de observabilidade e operação assistida da Sofia OS.

> Estado desta branch: arquitetura reconciliada com o runtime real de `eletrix-server` em 2026-08-28. A branch não está instalada em produção. O Sofia OS Gateway continua a ser a autoridade; o Control Center não pode tornar-se um caminho alternativo de execução.

## Arquitetura real

A topologia atual já não corresponde ao antigo modelo “um MCP local por card”. O runtime real é:

```text
ChatGPT
   ↓
Sofia OS Gateway :8770
   ↓
contracts / approvals / audit
   ↓
providers especializados
   ↓
Unix sockets, containers e serviços systemd
   ↓
sistemas externos
```

Os providers de leitura e escrita são frequentemente separados. Exemplo: Gmail tem providers independentes para leitura, modificar, rascunhos e envio.

## Reconciliação de 2026-08-28

A auditoria live confirmou:

- Gateway `READY`, graph `PASS` e operations broker disponível;
- `pedrovault-mcp-production` healthy;
- `pedrovault-mcp-tunnel.service` active;
- `pedrovault-ops-broker.service` active;
- `sofia-ssh-mcp` healthy;
- `pedrovault-pc-edge-provider` healthy;
- providers reais de Calendar, Contacts, Drive, Elektro3, Gmail, Google Places, Sheets, Tasks, Trello e PrestaShop ativos;
- providers atuais usam predominantemente Unix sockets em `/run/pedrovault-provider/...`;
- vários containers `green`, `canary` e históricos continuam presentes, mas não são tratados como runtime canónico pelo Control Center.

Também foi confirmado que os antigos serviços/portas do Control Center não existem neste host:

```text
mcp-memory.service                 AUSENTE
mcp-google-analytics.service       AUSENTE
mcp-prestashop.service             AUSENTE
127.0.0.1:8765 / 8767 / 8769      AUSENTES
127.0.0.1:18103 / 18104 / 18105   AUSENTES
```

Por isso, os antigos cards Memory, Google Analytics e PrestaShop-single-MCP não podem ser usados como autoridade operacional.

## Inventário canónico

`runtime/sofia-os-canonical.json` é o inventário reconciliado usado pela branch.

Domínios atuais:

| Domínio | Componentes canónicos | Estado de integração Gateway |
|---|---:|---|
| Sofia OS Core | Gateway, Operations Broker, Secure Tunnel | exposto |
| Privileged SSH | `sofia-ssh-mcp` | exposto |
| PC Edge | `pedrovault-pc-edge-provider` | exposto |
| PrestaShop | 6 providers | exposto |
| Gmail | 4 providers | exposto |
| Google Calendar | 2 providers | exposto |
| Google Tasks | 2 providers | exposto |
| Google Sheets | 2 providers | exposto |
| Google Contacts | 1 provider | exposto |
| Google Drive | 1 provider | exposto |
| Google Places | 1 provider | exposto |
| Elektro3 | 1 provider | exposto |
| Trello | 1 provider read/write | **provider healthy; tools ainda não expostas pelo Gateway** |

Memory, Google Analytics e Host Tools não aparecem como domínios canónicos porque não existe runtime correspondente na arquitetura atual.

## PrestaShop real

PrestaShop é um domínio composto, não um MCP único:

- `pedrovault-prestashop-provider-production-r55` — leitura principal;
- `pedrovault-prestashop-sofiabridge-readonly-provider.service` — SofiaBridge read-only;
- `pedrovault-prestashop-catalog-status-provider.service` — alteração controlada de `active`;
- `pedrovault-prestashop-category-writer-r82` — Category Writer;
- `pedrovault-prestashop-seo-write-provider.service` — SEO controlado;
- `pedrovault-prestashop-product-description-write-provider.service` — descrição de produto controlada.

A health live confirmou os providers principais como `READY`/healthy.

## Trello

O provider Trello existe e está ativo:

```text
pedrovault-trello-readwrite-provider.service
/run/pedrovault-provider/trello-readwrite.sock
```

Readiness live confirmou leitura e escrita, com capabilities de boards/lists/cards, criação de card e atualização de card. No entanto, a lista de tools atual do Gateway ainda não contém `trello.*`. Por isso o inventário marca Trello como `gateway_exposed=false` e o Control Center não deve fingir que a integração está concluída.

## Registry legado

O registry hardcoded do `server.py` continua no ficheiro apenas como compatibilidade histórica. A branch candidata suprime explicitamente os cinco IDs obsoletos:

```text
host-tools
google-tasks
memory
google-analytics
prestashop
```

Os manifests correspondentes usam `runtime.enabled=false`. Um runtime desativado não pode declarar services, source probe, tool probe ou lifecycle.

`sofia_registry.py` remove esses IDs do registry em memória antes de o servidor candidato arrancar. Isto impede cards falsos e impede lifecycle baseado numa topologia inexistente.

## Vista do Control Center

A API candidata acrescenta:

```text
runtime_inventory
legacy_registry_reconciliation
```

A UI renderiza os domínios reais do inventário canónico. Durante esta fase, cada domínio é apresentado como `reconciled`: a topologia é canónica, mas o live health por componente ainda será ligado através de uma futura API de inventory/status do Gateway.

## Lifecycle

Lifecycle permanece **fail-closed**.

O mecanismo genérico `prepare → CONFIRMO → execute` continua disponível no código e o endpoint legado `/api/action` continua desativado. Porém:

- nenhum componente do inventário canónico tem `lifecycle_enabled=true`;
- o runner anterior das nove ações foi removido da branch;
- as antigas ações `provider.memory.*`, `provider.google-analytics.*` e `provider.prestashop.*` não são válidas para o runtime real;
- o operations broker de produção não foi alterado.

Só será criado lifecycle depois de o Gateway fornecer uma identidade canónica para cada provider/componente real.

## Runtime inventory contract

`sofia_runtime_inventory.py` valida:

- IDs de domínio únicos;
- IDs de componentes únicos por domínio;
- targets não reutilizados entre domínios;
- tipos de runtime conhecidos (`docker`, `systemd`, `remote`);
- roles controladas;
- presença dos 13 domínios reconciliados;
- ausência de Memory, Google Analytics e Host Tools como domínios atuais;
- lifecycle obrigatoriamente desativado nesta fase;
- lista exata dos IDs legados que devem ser suprimidos.

O inventário é topologia, não snapshot de health. Estados efémeros não são gravados no ficheiro.

## Gateway health e client

`sofia_gateway_health.py` continua a consultar apenas:

```text
http://127.0.0.1:8770/ready
```

`sofia_gateway_client.py` continua limitado a:

```text
http://127.0.0.1:8770/mcp
```

Ambos exigem HTTP loopback e paths exatos. O Control Center não recebe liberdade para chamar hosts arbitrários.

## Segurança

Mantém-se:

- bind do Control Center em loopback;
- Gateway-only para ações materiais;
- `/api/action` legado desativado no entrypoint candidato;
- sem fallback silencioso para `systemctl` direto;
- manifests sem secrets;
- direct external exposure proibido;
- CI sem deploy e com `contents: read`.

Antes de qualquer deploy do Control Center ainda falta:

- remover o bearer reutilizável embebido no HTML legado;
- autenticar a sessão/UI corretamente;
- validar `Host` e `Origin`;
- adicionar proteção CSRF;
- ligar live health dos componentes do inventário ao Gateway;
- só depois desenhar lifecycle para identities reais;
- testar rollback.

## CI

`.github/workflows/sofia-control-center-ci.yml` valida:

- compilação dos módulos Python;
- manifests e supressão do registry legado;
- inventário canónico e os 13 domínios;
- lifecycle desativado em todos os componentes reconciliados;
- ausência dos runners antigos de lifecycle incorreto;
- rendering da vista por domínios;
- testes unitários;
- JSON do inventário;
- `bash -n` do instalador.

Não existe qualquer passo de deploy.

## Instalação candidata

`scripts/install_local.sh` instala também:

- `sofia_runtime_inventory.py`;
- `runtime/sofia-os-canonical.json`.

**Não executar em produção sem validação e aprovação explícitas.**

## Próxima sequência

1. criar no Gateway uma API read-only `provider inventory/status` canónica;
2. alimentar Process/Provider/Source/Gateway health por componente real;
3. expor Trello no Gateway ou marcar formalmente a integração como incompleta;
4. desenhar lifecycle apenas para components/IDs canónicos;
5. hardening Host/Origin/CSRF/autenticação;
6. rever e remover containers green/canary/históricos depois de confirmar que não são necessários;
7. testes end-to-end e rollback;
8. só depois preparar PR/merge/deploy.
