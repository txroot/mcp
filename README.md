# Microlumin MCPs

Repositório central para o código, documentação e procedimentos de instalação dos MCPs usados pela Microlumin/Eletrix.

## Objetivo

Os MCPs podem hoje correr num único computador, mas **não devem depender desse computador**. Cada integração deve ser reinstalável noutro host a partir deste repositório e da configuração local adequada.

O repositório guarda:

- código dos MCP servers;
- bridges/adapters necessários para chegar aos sistemas de origem;
- documentação de arquitetura e segurança;
- exemplos de configuração sem segredos;
- unidades/instaladores systemd;
- perfis de tunnel-client sem credenciais;
- health checks e procedimentos de teste;
- instruções de instalação, recuperação e migração.

O repositório **não guarda** passwords, tokens, API keys, ficheiros de credenciais, chaves privadas ou dumps de bases de dados.

## MCPs

| MCP | Estado no repositório | Função |
|---|---|---|
| PrestaShop Eletrix | Operacional | Operação, encomendas, carrinhos, catálogo, stock e auditoria de qualidade |
| MCP Control Center | Operacional | Gestão central dos MCPs locais |
| Interactive Terminal | Operacional | PTYs persistentes partilhados entre ChatGPT e Control Center |

Os restantes MCPs locais serão migrados para esta estrutura progressivamente.

## Estrutura

```text
mcp/
├── README.md
├── docs/
│   ├── architecture.md
│   ├── inventory.md
│   └── migration.md
├── control-center/
├── terminal/
└── prestashop/
    ├── README.md
    ├── server.py
    ├── prestashop_client.py
    ├── requirements.txt
    ├── .env.example
    ├── bridge/
    ├── scripts/
    ├── systemd/
    ├── tunnel/
    └── tests/
```

## Convenções

1. **Read-only por defeito.** Um MCP de consulta não recebe credenciais com permissões de escrita.
2. **Sem SQL arbitrário.** Bases de dados de produção são expostas através de queries/endpoints allow-listed.
3. **Segredos fora do Git.** Configuração sensível fica em `~/.config/<mcp>/` com permissões restritas.
4. **Serviços persistentes.** MCP e túnel são geridos por `systemd --user` quando aplicável.
5. **MCP Control Center.** Todo MCP instalado neste host deve ser integrado no Control Center com estado, health, logs e Start/Stop/Restart.
6. **Portabilidade.** O README de cada MCP deve permitir reconstruir a instalação num novo computador.
7. **Verificação antes de produção.** Bridge, permissões, health e tools são testados antes de expor um novo MCP pelo túnel.


## Interactive Terminal MCP — especificação operacional

O **Interactive Terminal MCP** fornece sessões Linux PTY reais e persistentes, partilhadas entre o utilizador no MCP Control Center e o ChatGPT através do OpenAI Secure Tunnel.

### Arquitetura

```text
Utilizador / browser
        |
        v
MCP Control Center :18100
        |
        | proxy autenticado
        v
Terminal Admin API :18107
        |
        +---------------------+
                              |
ChatGPT                       |
   |                          |
   v                          v
OpenAI Secure Tunnel ---> Terminal MCP :8770
                              |
                              v
                         PTY Linux real
                              |
                              v
                 bash / ssh / serial / REPL /
                 idf.py monitor / logs / etc.
```

O Control Center e o ChatGPT **não têm shells separadas**. Ambos operam sobre a mesma sessão PTY e veem o mesmo processo, input e output.

### Identificação humana e timestamps

Cada PTY recebe dois identificadores:

- `session_id` técnico, no formato `term_<hex>`;
- `terminal_code` humano de 4 caracteres, por exemplo `K7M4`, evitando caracteres ambíguos (`0`, `1`, `I`, `O`).

O código curto é único entre as sessões atualmente conhecidas e pode ser usado onde o backend aceita `session_id`. Em mensagens ao utilizador, o ChatGPT deve preferir o código curto (por exemplo, “usa o terminal `K7M4`”) e reservar o ID longo para diagnóstico.

O Control Center mostra um relógio local contínuo (`YYYY-MM-DD HH:MM:SS`), timestamps de criação e última atividade e marcadores de intervenção com identidade visual distinta: timestamp neutro, `● USER` em cyan e `✦ AI` em violeta. Esses marcadores são side-band: não alteram os bytes enviados à PTY. O backend guarda apenas `actor`, timestamp, sequência e cursor — **nunca o conteúdo digitado** — para que passwords de `sudo` e outros segredos não sejam capturados pelo mecanismo de timestamp. O header mantém o controlo da sidebar e `Interactive Terminal` à esquerda e `← MCP Control Center` à direita; criar/refrescar/configurar espera pertence à sidebar. Em mobile a sidebar funciona como drawer. Depois de input, o browser faz leituras imediatas em burst para reduzir o atraso de eco sem implementar local echo, preservando o comportamento seguro de passwords do PTY.

### Modelo de sessão

Cada sessão recebe um ID aleatório `term_<hex>`, nome, PID, cwd, estado, cursores de output e um buffer circular em memória. Por defeito:

- máximo de 16 sessões vivas;
- buffer máximo de 2 MiB por sessão;
- cwd limitado ao `HOME` do utilizador Unix;
- execução inicial com as permissões desse utilizador, sem elevação automática para root;
- `sudo` interativo é suportado para utilizadores autorizados: a password é sempre introduzida localmente pelo utilizador no xterm do Control Center e nunca deve ser pedida, transmitida ou guardada pelo ChatGPT;
- fechar/recarregar o browser não termina a sessão;
- reiniciar/parar `mcp-terminal.service` ou reiniciar o host termina as PTYs existentes.

O output é lido através de **cursores de bytes**. Um consumidor guarda o último `cursor` recebido e usa-o em leituras seguintes para obter apenas o output novo.

### Tools MCP

| Tool | Semântica |
|---|---|
| `terminal_create` | Cria uma PTY persistente. Sem `command`, abre uma login shell. |
| `terminal_list` | Lista sessões, estado, PID, cwd e cursores. |
| `terminal_read` | Lê output incremental sem bloquear. |
| `terminal_wait` | Fica bloqueado até existir output novo, a sessão terminar ou expirar o timeout. |
| `terminal_write` | Envia texto/teclas UTF-8 para a PTY. Incluir `\n` quando é necessário Enter. |
| `terminal_resize` | Altera linhas/colunas e envia `SIGWINCH`. |
| `terminal_signal` | Envia `INT`, `TERM`, `HUP`, `QUIT` ou `KILL` ao grupo de processos. |
| `terminal_close` | Termina o processo, mas mantém a sessão e o respetivo buffer na lista. |
| `terminal_delete` | Termina se necessário e remove a sessão e o respetivo buffer. |

### Conversa interativa ChatGPT ↔ terminal

Uma PTY persistente, por si só, **não mantém o ChatGPT a executar depois de uma resposta ser finalizada**. Para uma conversa contínua no terminal, a interação deve decorrer dentro de uma resposta ChatGPT ainda aberta, usando `terminal_wait` em ciclo.

Fluxo recomendado:

```text
1. terminal_read -> obter output inicial e cursor C0
2. terminal_wait(after_cursor=C0, timeout_seconds=20)
3. se timeout:
      voltar imediatamente a terminal_wait com o mesmo cursor
4. se chegou output do utilizador:
      processar apenas o output novo
      responder com terminal_write
      avançar o cursor para além do output/eco da própria resposta
      voltar a terminal_wait
5. só finalizar a resposta ChatGPT quando o utilizador enviar
   o marcador de saída acordado, por exemplo: FECHAR TESTE
```

`terminal_wait` tem timeout técnico curto de propósito; o timeout **não significa fim da conversa**. Num modo de interação persistente, o caller deve renovar a espera enquanto a resposta ChatGPT continuar ativa. Separadamente, cada sessão tem um **timeout lógico de intervenção** (por defeito 1 hora). O MCP mantém esse deadline entre chamadas curtas e devolve `intervention_timed_out=true` quando termina. A PTY permanece aberta. O valor pode ser definido no Control Center ou sobreposto pelo ChatGPT através de `intervention_timeout_seconds`; `0` significa sem limite lógico.

Um protocolo de demonstração simples pode marcar mensagens assim:

```text
[ANDRE -> CHATGPT] mensagem do utilizador
[CHATGPT -> ANDRE] resposta do ChatGPT
```

O ChatGPT deve evitar interpretar como nova mensagem do utilizador o eco produzido pela sua própria escrita na PTY. A forma mais segura é controlar corretamente os cursores e, quando necessário, usar marcadores explícitos.

### Limite importante do modelo de execução

O Interactive Terminal não transforma o ChatGPT num daemon autónomo. Existem dois modos distintos:

1. **Sessão PTY persistente** — o processo continua ativo mesmo que o browser seja fechado ou o ChatGPT termine uma resposta.
2. **Turno ChatGPT persistente** — o ChatGPT pode ficar à espera e interagir repetidamente apenas enquanto a resposta atual permanece em execução, renovando `terminal_wait`.

Depois de uma resposta ChatGPT ser finalizada, não existem novas chamadas ao MCP até ocorrer um novo turno do ChatGPT. Para verdadeira automação autónoma/contínua é necessário um agente/serviço próprio, e não apenas a PTY.

### Limpeza automática e paralelismo

O Terminal MCP elimina automaticamente sessões já fechadas depois de um período configurável, por defeito **24 horas após `closed_at`**. O Control Center disponibiliza Off, 6 h, 12 h, 24 h, 3 d, 7 d e 30 d. Sessões `running` nunca são apagadas automaticamente, mesmo que não produzam output durante muito tempo. A política fica persistida nas settings do MCP e o sweep corre periodicamente no backend.

O modelo deve explorar paralelismo quando existirem tarefas independentes: múltiplas sessões/processos podem e devem ser usadas para leituras, builds, testes ou análises independentes, com reconciliação dos resultados. Não paralelizar operações com dependências de ordem, escritas concorrentes sobre os mesmos ficheiros/estado Git, migrações de base de dados, operações destrutivas ou acesso ao mesmo recurso físico/partilhado sem garantia explícita de segurança. Usar paralelismo limitado e intencional.

Esta regra está nas instruções do MCP 1.4.0. Como o app ChatGPT Business publicado usa um snapshot congelado, a próxima recriação/publicação do Plugin deve incluir explicitamente esta política para garantir que o modelo a recebe também pelo metadata publicado.

### Gestão da lista de terminais

A sidebar de terminais no desktop é redimensionável com o rato entre 280 e 600 px (340 px por defeito), guarda a largura no browser e permite repor o default com duplo clique no separador. A pesquisa compacta filtra por nome, código curto, ID técnico, cwd ou estado. **Clear closed terminals** remove em bloco apenas sessões terminadas, após confirmação, sem tocar nas sessões `running`.

Regra para o ChatGPT: persistência deve ser intencional. Para diagnósticos one-shot, preferir sessões ligadas ao comando que terminam naturalmente. Se abrir uma shell interativa, deve chamar `terminal_close` quando o trabalho acabar, exceto quando exista um motivo concreto para manter a PTY: processo/log ativo, continuidade útil ou intervenção física/do utilizador esperada. Fechar preserva o buffer; apagar é uma decisão de limpeza separada.

### MCP Control Center

A UI do Terminal está disponível em `http://127.0.0.1:18100/terminal` e permite:

- criar e anexar a sessões;
- escrever e visualizar output em xterm;
- redimensionar a PTY;
- enviar `Ctrl+C` e `TERM`;
- **Close**: terminar mantendo histórico/buffer;
- **Delete**: terminar, se necessário, e remover definitivamente a sessão da lista;
- reanexar a uma sessão depois de navegar para outra página ou recarregar o browser.

### Portas e fronteiras de segurança

| Porta | Serviço | Exposição |
|---:|---|---|
| `8770` | Terminal MCP Streamable HTTP | loopback; exposto ao ChatGPT apenas através do Secure Tunnel |
| `18107` | Terminal local admin/PTY API | apenas loopback; nunca expor pelo tunnel |
| `18108` | health/admin do `tunnel-client` | apenas loopback |
| `18100` | MCP Control Center | apenas loopback |

A API `18107` exige `X-Terminal-Admin-Token`. O browser não recebe esse token: comunica com o proxy autenticado do Control Center. O Secure Tunnel aponta exclusivamente para o MCP em `8770`.

O Terminal MCP é deliberadamente poderoso: qualquer comando executável pelo utilizador Unix pode alterar ficheiros, iniciar/parar processos acessíveis e comunicar com hardware. O serviço permite o fluxo normal de `sudo` (`NoNewPrivileges=false`) para sessões de desenvolvimento, mas não recebe privilégios root por defeito. Quando `sudo` pedir autenticação, a password deve ser digitada **apenas** pelo utilizador diretamente no terminal do Control Center; nunca deve passar pelo chat, por `terminal_write`, por ficheiros ou por logs. As operações devem permanecer visíveis e auditáveis e as regras de autorização do projeto continuam a aplicar-se.

### OpenAI Secure Tunnel e discovery

O serviço `mcp-terminal-tunnel.service` depende do Terminal MCP. O unit espera pelo health check local antes de iniciar o tunnel, evitando uma race em que o tunnel faz discovery antes de `8770/18107` estarem prontos.

O servidor publica uma versão MCP explícita para ajudar clientes/tunnels a distinguir revisões de schema. No workspace ChatGPT Business, a app publicada usa um snapshot congelado das tools. Alterar o MCP ou a versão anunciada pelo servidor **não atualiza esse snapshot**. Para alterações de tools/inputs, a revisão deve ser testada em Developer mode e depois recriada/republicada como nova versão da app; a app publicada anterior deve permanecer ativa até a substituta estar validada.

Depois de alterar o schema das tools do MCP, uma conversa ChatGPT já aberta pode continuar com o schema antigo em cache. Nesse caso:

- confirmar primeiro que o MCP local expõe as tools novas;
- confirmar `18108/readyz` = `ready`;
- iniciar uma nova conversa ou reconectar/recarregar a app **Interactive Terminal** para forçar novo discovery.

### Critérios mínimos de aceitação

Antes de considerar uma alteração ao Interactive Terminal concluída devem passar, no mínimo:

- `pytest` do `terminal/`;
- `py_compile` dos módulos Python alterados;
- `git diff --check`;
- discovery MCP real em `http://127.0.0.1:8770/mcp`;
- health local do Terminal e `readyz` do tunnel;
- teste create → write → read;
- teste de `terminal_wait` bloqueado que acorda apenas quando chega output;
- teste `Close` vs `Delete`;
- teste visual no Chrome da UI do Control Center quando a alteração afeta frontend;
- para alterações de tunnel/app, teste ChatGPT → OpenAI tunnel → MCP → PTY quando possível.

A especificação detalhada de instalação e implementação está em [`terminal/README.md`](terminal/README.md).

## Instalar noutro computador

Ver [`docs/migration.md`](docs/migration.md). Cada subdiretório tem também instruções específicas.

## Segurança

Se um segredo for acidentalmente commitado, removê-lo do histórico **não é suficiente**: a credencial deve ser imediatamente revogada/rotacionada.

### Compatibilidade com schemas publicados antigos

Para instalações ChatGPT Business cujo snapshot ainda não exponha `terminal_wait`, a tool MCP `terminal_read` tem um modo retrocompatível: sem `after_cursor` faz leitura imediata; com `after_cursor` bloqueia por uma janela técnica curta (20 s) e devolve `timed_out` / `intervention_timed_out`. O caller renova `terminal_read` com o cursor devolvido enquanto a intervenção lógica continuar ativa. O endpoint REST usado pelo Control Center continua não bloqueante.

**Validado operacionalmente em 2026-08-27:** o conector ChatGPT ainda com o snapshot antigo de 7 tools bloqueou em `terminal_read(after_cursor=...)` até chegar novo output, acordou com o marcador esperado e, num teste sem output, devolveu `timed_out=true` mantendo `intervention_timed_out=false`, `wait_state=waiting` e a PTY ativa. O utilizador confirmou posteriormente que o fluxo funciona no uso real. Assim, `terminal_wait` continua a ser a API explícita/preferida para novas revisões, mas já não é requisito para espera bloqueante em instalações com schema antigo.
