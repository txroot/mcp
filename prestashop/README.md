# PrestaShop Eletrix MCP

MCP **read-only** para informação operacional, estatística e auditoria do PrestaShop Eletrix.

## Casos de uso

- observar carrinhos abandonados;
- consultar encomendas e respetivos estados;
- obter indicadores operacionais por período;
- contar produtos, combinações/SKUs e stock;
- procurar e ler fichas de produto;
- auditar qualidade do catálogo;
- alimentar dashboards e análises em conjunto com GA4.

## Arquitetura

```text
ChatGPT
  |
  | secure tunnel
  v
tunnel-client
  |
  v
PrestaShop MCP (localhost)
  |
  | HTTPS + Bearer token
  v
prestashop_mcp_bridge.php
  |
  | MariaDB account: SELECT only
  v
PrestaShop database
```

A bridge não aceita SQL fornecido pelo cliente. Cada `mode` corresponde a uma query fixa e parametrizada.

## Tools MVP

- `prestashop_health`
- `shop_overview`
- `orders_list`
- `order_details`
- `abandoned_carts`
- `products_summary`
- `products_search`
- `product_details`
- `stock_summary`
- `product_quality_audit`
- `product_duplicates`

## Definição de carrinho abandonado

No MVP considera-se abandonado um carrinho que:

1. tem pelo menos uma linha em `cart_product`;
2. não tem uma encomenda associada pelo `id_cart`;
3. não é atualizado há pelo menos `min_age_hours` (2 h por defeito);
4. não é mais antigo que `max_age_days` (30 dias por defeito).

O valor apresentado é uma **estimativa de catálogo atual sem IVA/portes/descontos**, não um total contabilístico do checkout.

## Auditoria de qualidade

A auditoria assinala, entre outros:

- referência em falta ou duplicada;
- EAN em falta ou formato suspeito;
- fabricante/marca em falta;
- descrição ou descrição curta em falta;
- imagem em falta;
- meta title/meta description em falta;
- preço não positivo;
- produto ativo sem stock;
- slug duplicado;
- referência/EAN duplicados em produtos e combinações.

As regras são indicadores de revisão, não decisões automáticas de alteração do catálogo. A completude/anomalias e os duplicados são consultados em tools separadas para manter as queries previsíveis numa base grande.

## Segurança

- conta MariaDB dedicada com `SELECT`/`USAGE` apenas;
- `SET SESSION TRANSACTION READ ONLY` quando suportado;
- HTTPS obrigatório;
- Bearer token validado por hash SHA-256 no servidor;
- queries fixas e parametrizadas;
- sem operações de escrita no MCP;
- sem segredos neste repositório;
- listagens minimizam PII; dados pessoais completos só aparecem onde são operacionalmente necessários.

## Configuração local

```bash
mkdir -p ~/.config/prestashop-mcp
cp .env.example ~/.config/prestashop-mcp/runtime.env
chmod 600 ~/.config/prestashop-mcp/runtime.env
```

Editar o ficheiro e preencher `PRESTASHOP_BRIDGE_TOKEN` fora do Git.

## Bridge no servidor PrestaShop

A bridge é publicada no diretório protegido junto da bridge existente, juntamente com o ficheiro real `.prestashop_orders_bridge.env` já usado pelo acesso SELECT-only. O deployment usa um **nome versionado pelo hash do ficheiro** para evitar servir código antigo por causa do opcode cache do PHP no hosting.

Exemplo:

```text
.../public_html/shop/_orders_check/
├── payments_bridge.php
├── prestashop_mcp_bridge_<hash>.php
├── .prestashop_orders_bridge.env
└── .htaccess
```

Configuração FTP local (fora do Git):

```text
~/.config/mcp-ftp-eletrix/runtime.env
```

com `FTP_HOST`, `FTP_USER` e `FTP_PASSWORD`, permissões `600`. Para publicar e ativar a nova versão:

```bash
python scripts/deploy_bridge.py --activate
systemctl --user restart mcp-prestashop.service
```

O script nunca imprime a password e atualiza apenas o `PRESTASHOP_BRIDGE_URL` no runtime env local.

Nunca publicar o conteúdo do `.env`. Confirmar por HTTP que o ficheiro retorna 403/404.

## Instalação local

```bash
./scripts/install_local.sh
```

O instalador cria a `.venv`, instala dependências e cria `mcp-prestashop.service`. É necessário preencher primeiro o runtime env.

## Smoke test

```bash
source .venv/bin/activate
set -a
source ~/.config/prestashop-mcp/runtime.env
set +a
python -c 'from prestashop_client import health_check; print(health_check()["ok"])'
```

O resultado esperado é `True`; o utilizador SQL deve coincidir com `PRESTASHOP_EXPECTED_DB_USER` e os grants aceites são apenas `USAGE`/`SELECT`. Se a conta ganhar uma permissão de escrita, o health falha.

## Tunnel

O perfil de exemplo está em `tunnel/prestashop.yaml.example`. O `tunnel_id` é criado/atribuído no control plane e a API key permanece num runtime env local partilhado com `tunnel-client`.

## MCP Control Center

No host de produção local, o MCP deve aparecer no Control Center com:

- estado do serviço MCP;
- estado do tunnel;
- health/ready;
- logs;
- Start/Stop/Restart;
- Admin UI do tunnel.

## Migração

Num novo PC: clone, runtime env local, bridge health, instalador, tunnel, Control Center e smoke test. Nenhuma password precisa de estar no repositório.
