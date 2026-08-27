# Arquitetura dos MCPs

## Padrão local

```text
ChatGPT / agente
       |
       | OpenAI secure tunnel
       v
tunnel-client
       |
       | localhost
       v
MCP server
       |
       | API/bridge read-only
       v
Sistema de origem
```

O MCP server traduz intenções operacionais em tools tipadas. O acesso ao sistema de origem deve ter o menor privilégio possível.

## Componentes por MCP

- **server**: tools MCP, validação de parâmetros e semântica de negócio;
- **client/adapter**: comunicação com a fonte externa;
- **bridge**: quando necessário, superfície HTTPS restrita junto da fonte;
- **systemd**: execução persistente e reinício automático;
- **tunnel-client**: ligação outbound ao control plane;
- **MCP Control Center**: operação local, health, logs e controlo dos serviços.

## Portas

As portas são detalhes de deployment e devem ser documentadas, mas não assumidas globalmente pelo código. No host de desenvolvimento atual são reservadas sequencialmente para evitar colisões.

## Segredos

Nunca entram no repositório. Usar ficheiros em `~/.config/<mcp>/` com `chmod 600`, `EnvironmentFile=` do systemd ou secret stores equivalentes.


## Interactive Terminal MCP

O terminal interativo usa duas superfícies sobre o mesmo gestor de PTYs:

```text
ChatGPT -- OpenAI tunnel --> MCP :8770 --+
                                         |
MCP Control Center :18100 --> local API :18107 --> PTY manager --> shell/processo
```

A API local de PTY (`18107`) e o Control Center permanecem em loopback e não são publicados pelo tunnel. O browser usa o token do Control Center, que faz proxy das operações. A sessão é única e partilhada: input do utilizador e input via MCP chegam ao mesmo PTY.
