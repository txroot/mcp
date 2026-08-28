# Sofia Control Center

Interface local de observabilidade e operação assistida da Sofia OS.

> Estado desta branch: arquitetura reconciliada com o runtime real de `eletrix-server` em 2026-08-28. A branch não está instalada em produção. O Sofia OS Gateway continua a ser a autoridade e o Control Center não pode tornar-se um caminho alternativo de execução.

## Arquitetura real

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

O antigo modelo “um MCP local por card” deixou de representar o runtime real. Leitura e escrita são frequentemente providers separados; Gmail, por exemplo, tem providers distintos para leitura, modificar, rascunhos e envio.

## Reconciliação de 2026-08-28

A auditoria live confirmou Gateway `READY`, graph `PASS`, Operations Broker disponível, secure tunnel ativo, SSH e PC Edge healthy e providers reais de Calendar, Contacts, Drive, Elektro3, Gmail, Google Places, Sheets, Tasks, Trello e PrestaShop.

Também confirmou que os antigos serviços/portas `mcp-memory`, `mcp-google-analytics` e `mcp-prestashop` não existem neste host. Por isso, esses cards antigos não podem ser autoridade operacional.

O registry legado mantém-se apenas para compatibilidade histórica. A branch suprime explicitamente:

```text
host-tools
google-tasks
memory
google-analytics
prestashop
```

Os manifests correspondentes usam `runtime.enabled=false`, impedindo services, source probes, tool probes ou lifecycle nessa topologia obsoleta.

## Inventário canónico

`runtime/sofia-os-canonical.json` contém a topologia reconciliada. Tem 13 domínios:

| Domínio | Componentes canónicos | Gateway |
|---|---:|---|
| Sofia OS Core | Gateway, Operations Broker, Secure Tunnel | exposto |
| Privileged SSH | 1 | exposto |
| PC Edge | 1 | exposto |
| PrestaShop | 6 | exposto |
| Gmail | 4 | exposto |
| Google Calendar | 2 | exposto |
| Google Tasks | 2 | exposto |
| Google Sheets | 2 | exposto |
| Google Contacts | 1 | exposto |
| Google Drive | 1 | exposto |
| Google Places | 1 | exposto |
| Elektro3 | 1 | exposto |
| Trello | 1 read/write | provider healthy; tools Gateway pendentes |

Memory, Google Analytics e Host Tools não são domínios canónicos atuais porque não existe runtime correspondente.

PrestaShop é um domínio composto: leitura principal, SofiaBridge read-only, Catalog Status, Category Writer, SEO Writer e Product Description Writer.

## Gateway provider inventory/status

A branch inclui agora o contrato candidato para uma nova tool read-only:

```text
gateway_provider_inventory
```

O código Gateway candidato está em `gateway/provider_inventory.py` e segue o mesmo padrão `READ_ONLY_LOCAL` usado pelas tools read-only do Gateway de produção.

A resposta é minimizada. Para cada componente expõe apenas:

- identidade canónica `domain/component`;
- domínio e role;
- runtime kind e target canónico;
- se está exposto pelo Gateway;
- readiness `healthy`, `degraded`, `unhealthy` ou `unknown`;
- contrato simbólico usado como evidência;
- lifecycle.

Não copia payloads completos de readiness. Credenciais, OAuth metadata, token IDs, paths de credenciais, fingerprints, paths do Vault, stack traces e mensagens arbitrárias de exceção ficam fora da resposta.

### Resolver boundary

O inventário não executa uma tool indicada por uma string vinda do JSON. Cada provider tem de ser ligado explicitamente a um resolver read-only com uma identidade canónica como:

```text
sofia-core/gateway
mail/read
mail/send
prestashop/category-writer
```

Resolver ausente = `unknown`. Nunca existe “healthy por defeito”. Uma falha de resolver é reduzida à classe do erro, sem copiar o texto da exceção.

O wiring de produção está documentado em `gateway/README.md` e continua fora do instalador do Control Center.

## Consumo pelo Control Center

`sofia_gateway_client.py` permite agora chamar `gateway_provider_inventory` além das tools lifecycle já allowlisted. O cliente continua limitado a `http://127.0.0.1:8770/mcp`; não aceita hosts externos nem nomes arbitrários de tools.

`sofia_provider_inventory.py` valida a resposta live contra a baseline reconciliada. O Gateway não pode alterar silenciosamente:

- inventory ID ou host;
- conjunto de domínios;
- conjunto/identidade dos providers;
- role;
- runtime kind;
- runtime target;
- Gateway exposure;
- status contract;
- lifecycle.

Se qualquer uma destas identidades divergir, o Control Center rejeita o documento live e usa a baseline reconciliada.

Enquanto a nova tool ainda não estiver instalada no Gateway real, o Control Center apresenta a mesma estrutura operacional, mas com:

```text
source = reconciled_baseline
live = false
readiness = unknown
```

Assim o dashboard não quebra e também não inventa estados verdes.

A API candidata passa a expor:

```text
runtime_inventory
runtime_inventory_status
legacy_registry_reconciliation
```

Quando o Gateway live estiver disponível, `runtime_inventory_status.source=gateway_live`. Até lá fica `reconciled_baseline`.

## Lifecycle

Lifecycle permanece **fail-closed**.

- `/api/action` legado continua desativado no entrypoint candidato;
- não existe fallback silencioso para `systemctl` direto;
- nenhum componente canónico tem `lifecycle_enabled=true`;
- o runner anterior das nove ações incorretas foi removido;
- as antigas ações `provider.memory.*`, `provider.google-analytics.*` e `provider.prestashop.*` não são válidas para o runtime real;
- o Operations Broker de produção não foi alterado.

O novo provider inventory devolve sempre `lifecycle.enabled=false` e `actions=[]` nesta fase. O Control Center rejeita um inventário live que tente mudar isso.

## Gateway health

`sofia_gateway_health.py` consulta apenas:

```text
http://127.0.0.1:8770/ready
```

Mantém Process / Provider / Source / Gateway health separados e não trata `unknown` como saudável.

## Segurança

Baseline desta branch:

- Control Center em loopback;
- Gateway health e MCP apenas em loopback;
- tool allowlist explícita no cliente;
- provider inventory read-only e minimizado;
- status resolvers explicitamente ligados por identidade;
- sem dynamic tool lookup;
- sem secrets nos manifests/inventory;
- direct external exposure proibido;
- lifecycle desligado para o inventário canónico;
- `/api/action` legado desativado;
- sem fallback para `systemctl` direto;
- CI sem deploy e com `contents: read`.

Antes de qualquer deploy do Control Center ainda é obrigatório remover o bearer reutilizável embebido no HTML legado, autenticar corretamente a sessão/UI, validar `Host`/`Origin`, adicionar CSRF e executar testes end-to-end/rollback.

## CI

`.github/workflows/sofia-control-center-ci.yml` valida:

- compilação dos módulos Control Center e do candidato Gateway provider inventory;
- manifests e supressão do registry legado;
- os 13 domínios reconciliados;
- provider inventory read-only;
- `unknown` para resolvers não ligados;
- minimização de credenciais/fingerprints/erros;
- binding da resposta live à identidade reconciliada;
- lifecycle desativado em todos os components;
- ausência dos runners antigos de lifecycle incorreto;
- testes unitários;
- JSON do inventário;
- `bash -n` do instalador.

Não existe qualquer passo de deploy.

## Instalação candidata do Control Center

`scripts/install_local.sh` instala `sofia_provider_inventory.py` e a baseline `runtime/sofia-os-canonical.json`.

Não instala `control-center/gateway/`; esse código pertence a uma futura alteração explícita da imagem do Sofia OS Gateway.

**Não executar o instalador em produção sem validação e aprovação explícitas.**

## Próxima sequência

1. ligar todos os components canónicos a resolvers read-only explícitos no candidato Gateway;
2. construir/testar uma imagem Gateway canary com `gateway_provider_inventory`;
3. comparar a resposta canary com o runtime live e o audit ledger;
4. alimentar a UI do Control Center com readiness live por domínio/provider;
5. expor Trello formalmente no Gateway ou manter `gateway_exposed=false`;
6. só depois desenhar lifecycle para identities reais;
7. hardening Host/Origin/CSRF/autenticação;
8. rever e remover containers green/canary/históricos quando comprovadamente desnecessários;
9. testes end-to-end, rollback e só depois PR/merge/deploy.
