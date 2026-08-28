# Sofia Control Center

Interface local de observabilidade e operação assistida dos providers da Sofia OS.

> Estado desta branch: migração gateway-first em desenvolvimento. A branch não está instalada em produção. O Sofia OS Gateway é a autoridade alvo; o Control Center não pode tornar-se um caminho alternativo de execução.

## Arquitetura alvo

```text
Sofia Control Center
        ↓
Sofia OS Gateway
        ↓
Capability / Contract
        ↓
Operations Broker
        ↓
Provider
        ↓
Sistema externo
```

Ações materiais seguem `prepare → CONFIRMO → execute → audit → postflight`. Não existe fallback intencional para lifecycle direto quando a mediação do Gateway não está disponível.

## Estado desta branch

### Implementado

- `ProviderManifest` e `RuntimeContract`;
- enforcement `FULL`, `CONTROLLED`, `ADVISORY`, `UNSUPPORTED`;
- health separado em Process / Provider / Source / Gateway;
- Gateway health real via `http://127.0.0.1:8770/ready`;
- Gateway MCP client stdlib via `http://127.0.0.1:8770/mcp`;
- URLs Gateway limitados a HTTP loopback e paths exatos;
- PrestaShop, Google Analytics e Memory manifest-driven;
- source-health allowlisted para PrestaShop e GA4;
- Memory com `source_health=false` sem inventar source probe;
- lifecycle `start/stop/restart` declarado nos três manifests;
- lifecycle capabilities `CONTROLLED`, risco `service_availability`, approval obrigatório;
- endpoint legado `/api/action` desativado no `SofiaHandler` candidato;
- endpoints `/api/lifecycle/prepare` e `/api/lifecycle/execute`;
- approval localmente ligado à preparação feita pela mesma instância do Control Center;
- UI two-phase que exige escrever `CONFIRMO` antes da execução;
- botões lifecycle só ficam ativos quando o Gateway anuncia a ação exata;
- runner Gateway candidato com allowlist fechada de providers/units;
- nove ações broker candidatas, sem unit ou comando arbitrário vindo da UI;
- CI GitHub Actions com compilação, manifests, lifecycle contract, testes e `bash -n`.

### Ainda não concluído

- o operations broker de produção ainda **não anuncia** as nove ações `provider.*.{start,stop,restart}`;
- por esse motivo, na branch candidata os botões lifecycle ficam fail-closed/desativados contra o Gateway atual;
- o runner e o fragmento de broker em `control-center/gateway/` ainda não foram instalados no Gateway de produção;
- bearer reutilizável continua embebido no HTML legado;
- Host/Origin/CSRF ainda não foram endurecidos;
- Host Tools e Google Tasks ainda precisam de manifest próprio;
- `provider-terminal-privileged` ainda não está integrado;
- não houve merge em `main`, deploy ou restart de produção.

## Providers migrados

| Provider | MCP local | Source health | Lifecycle |
|---|---|---|---|
| Memory | `127.0.0.1:8765/mcp` | não obrigatório | Gateway candidate |
| Google Analytics | `127.0.0.1:8767/mcp` | GA4 read-only | Gateway candidate |
| PrestaShop | `127.0.0.1:8769/mcp` | bridge read-only | Gateway candidate |

Host Tools e Google Tasks continuam em fallback de registry para observabilidade, mas o entrypoint Sofia não lhes concede lifecycle direto.

## Provider contract

`sofia_provider.py` define:

- `ProviderManifest`;
- `Capability`;
- `RuntimeContract`;
- `HealthContract`;
- níveis de enforcement;
- riscos e approval por capability;
- regras gateway-first.

Um runtime pode declarar:

- `registry_id`;
- services;
- profile/tunnel;
- endpoint MCP;
- health/admin;
- probe type;
- `source_probe` simbólico;
- tool discovery;
- lifecycle mapping.

Lifecycle é uma mapping fechada:

```json
{
  "lifecycle": {
    "start": "provider.memory.start",
    "stop": "provider.memory.stop",
    "restart": "provider.memory.restart"
  }
}
```

O parser exige as três ações em conjunto e exige identidade exata entre `runtime.registry_id` e o nome da operação Gateway. Um manifest Memory não pode, por exemplo, apontar `restart` para `provider.prestashop.restart`.

## Lifecycle mediado pelo Gateway

### Control Center

`sofia_lifecycle.py` implementa o fluxo em duas fases.

Preparação:

1. valida provider e ação contra o manifest;
2. calcula a ação exata `provider.<registry_id>.<action>`;
3. consulta `gateway_vm_status` pelo MCP do Gateway;
4. confirma que a ação está na allowlist live;
5. chama `gateway_prepare_operation`;
6. exige `effect_applied=false` e `confirmation_required=CONFIRMO`;
7. guarda localmente o approval com TTL limitado.

Execução:

1. exige approval ID válido;
2. exige literalmente `CONFIRMO`;
3. exige que o approval tenha sido preparado pela mesma instância do Control Center;
4. falha se o TTL local expirou;
5. chama `gateway_execute_operation`;
6. exige `outcome=PASS`, `effect_applied=true` e a mesma ação preparada;
7. remove o approval local após sucesso.

Não existe chamada `systemctl` em `sofia_lifecycle.py` ou no handler lifecycle do Control Center.

### Endpoint legado

O `server.py` legado continua no repositório para compatibilidade e contém a implementação histórica de `service_action()`.

No entrypoint candidato:

```text
legacy.service_action = _direct_lifecycle_disabled
```

Além disso, `SofiaHandler` intercepta `/api/action` e devolve HTTP `410 Gone`. Portanto, mesmo uma chamada manual ao endpoint histórico não executa lifecycle quando a branch candidata é o entrypoint ativo.

### UI

`sofia_ui.py` substitui os botões históricos por lifecycle Gateway-only.

Um botão só fica ativo quando:

- o provider tem manifest gateway-first;
- o manifest declara a ação;
- `/ready` anuncia a ação `provider.*` correspondente.

Ao clicar:

1. `/api/lifecycle/prepare`;
2. prompt explícito para escrever `CONFIRMO`;
3. `/api/lifecycle/execute`.

Se o Gateway não anunciar a ação, o botão permanece desativado e a API de preparação também volta a validar a allowlist live.

## Gateway MCP client

`sofia_gateway_client.py` não depende do SDK `mcp`.

O deployment atual do Gateway foi validado com Streamable HTTP stateless e JSON em:

```text
http://127.0.0.1:8770/mcp
```

O cliente aceita apenas três tools:

- `gateway_vm_status`;
- `gateway_prepare_operation`;
- `gateway_execute_operation`.

Não pode chamar shell, Vault writes ou outras tools por nome arbitrário. O URL tem de ser HTTP loopback, com porta explícita e path exato `/mcp`. A resposta também tem limite de tamanho e parsing fail-closed.

## Gateway health

`sofia_gateway_health.py` consulta:

```text
http://127.0.0.1:8770/ready
```

Retém apenas evidência necessária:

- `service_id`;
- `status`;
- `graph_outcome`;
- broker available;
- estado/health de `mcp_gateway`;
- `audit_outcome`;
- ações `provider.*` filtradas para disponibilidade visual de lifecycle.

Não replica paths de Vault, backups, hashes ou a allowlist operacional completa.

Classificação:

- `healthy`: Gateway `READY`, serviço running/healthy, graph `PASS`, broker disponível e audit `PASS`;
- `degraded`: runtime disponível mas graph/broker/audit não cumprem baseline;
- `unhealthy`: Gateway não READY, serviço não healthy/running ou probe inválido.

## Candidate Gateway lifecycle runner

`gateway/provider_lifecycle_runner.py` é um artefacto candidato, **não instalado em produção**.

Provider/unit allowlist:

```text
prestashop
  mcp-prestashop.service
  mcp-prestashop-tunnel.service

google-analytics
  mcp-google-analytics.service
  mcp-google-analytics-tunnel.service

memory
  mcp-memory.service
  mcp-memory-tunnel.service
```

O runner:

- aceita apenas esses três providers;
- aceita apenas `start`, `stop`, `restart`;
- não recebe nomes de units da UI;
- executa no user manager de `eletrix`;
- para `stop`, inverte a ordem para desligar tunnel antes do MCP;
- faz readback de estado antes/depois;
- exige postflight coerente;
- devolve resultado JSON limitado a dados operacionais do lifecycle.

`gateway/provider_lifecycle_actions.py` gera exatamente nove entradas candidatas para `ALLOWED_ACTIONS` do operations broker:

```text
provider.prestashop.start
provider.prestashop.stop
provider.prestashop.restart
provider.google-analytics.start
provider.google-analytics.stop
provider.google-analytics.restart
provider.memory.start
provider.memory.stop
provider.memory.restart
```

Cada comando é envolvido pelo runtime interlock existente. O broker continua a usar o contrato atual de `prepare_operation(action)` e `execute_operation(approval_id, CONFIRMO)`; não foi aberto um interface genérico de systemd.

## Estado live do Gateway

Durante o desenvolvimento deste bloco, o Gateway real foi verificado como operacional e o MCP expôs:

- `gateway_vm_status`;
- `gateway_prepare_operation`;
- `gateway_execute_operation`.

O broker de produção ainda não contém `provider.memory.restart` nem as restantes ações candidatas. Uma tentativa de preparação dessa ação foi recusada com `Ação fora da allowlist`, confirmando comportamento fail-closed antes de qualquer deploy do runner.

## Source health

`sofia_source_health.py` só executa probes explicitamente allowlisted pelo entrypoint:

- `google_analytics`;
- `prestashop`.

Memory declara `source_health=false` e não executa source probe.

## Quatro camadas de health

Cada item da API recebe:

```json
{
  "health_layers": {
    "process": {"state": "healthy", "required": true},
    "provider": {"state": "healthy", "required": true},
    "source": {"state": "unknown", "required": false},
    "gateway": {"state": "healthy", "required": true}
  }
}
```

O `state` legado `online/degraded/offline` permanece temporariamente para compatibilidade.

## Segurança

Baseline da branch:

- Control Center bind em loopback;
- Gateway health e MCP limitados a loopback;
- tool allowlist fechada no cliente Gateway;
- manifests não contêm secrets;
- direct external exposure proibido;
- lifecycle sem fallback direto;
- lifecycle operation ID ligado à identidade do provider;
- approval local ligado à preparação da mesma instância;
- `CONFIRMO` obrigatório;
- runner Gateway com provider/unit allowlist estática;
- runtime interlock previsto em todas as nove ações broker;
- CI sem deploy e com `contents: read`.

Antes de produção ainda é obrigatório:

- remover o bearer reutilizável embebido no HTML;
- autenticar a sessão/UI adequadamente;
- validar Host e Origin;
- adicionar proteção CSRF;
- instalar e testar o runner/broker lifecycle num ambiente isolado;
- validar owner/user-manager e permissions no host real;
- validar preflight/postflight de start/stop/restart reais;
- validar audit trail do broker;
- testar rollback para o entrypoint anterior.

## CI

`.github/workflows/sofia-control-center-ci.yml` valida:

- compilação de todos os módulos Control Center;
- compilação dos candidatos Gateway lifecycle;
- manifests dos três providers;
- identidade exata dos nove lifecycle action IDs;
- lifecycle capabilities `CONTROLLED` + approval + `service_availability`;
- source-health específico por provider;
- endpoints Gateway default loopback;
- presença da desativação do lifecycle legado;
- testes unitários de Gateway client, lifecycle controller, runner, manifests, health e UI;
- `bash -n` do instalador.

Não existe deploy no workflow.

## Instalação candidata do Control Center

`scripts/install_local.sh` instala os módulos Control Center, incluindo `sofia_gateway_client.py` e `sofia_lifecycle.py`.

Não instala os ficheiros de `control-center/gateway/`; esses artefactos pertencem a uma futura alteração explícita do Gateway/broker e exigem validação separada.

**Não executar o instalador em produção sem uma etapa explícita de validação e aprovação.**

## Próxima sequência

1. preparar deployment isolado do runner lifecycle e das nove ações no operations broker;
2. validar start/stop/restart reais num provider piloto, com audit e postflight;
3. hardening Host/Origin/CSRF/autenticação do Control Center;
4. migrar Host Tools e Google Tasks para manifests;
5. integrar `provider-terminal-privileged`;
6. testes end-to-end e rollback;
7. só depois preparar PR/merge/deploy de produção.
