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

## Instalar noutro computador

Ver [`docs/migration.md`](docs/migration.md). Cada subdiretório tem também instruções específicas.

## Segurança

Se um segredo for acidentalmente commitado, removê-lo do histórico **não é suficiente**: a credencial deve ser imediatamente revogada/rotacionada.
