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
