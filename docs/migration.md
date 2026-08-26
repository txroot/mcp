# Instalação e migração para outro computador

## Princípio

Um novo host deve conseguir reconstruir cada MCP a partir de:

1. clone deste repositório;
2. dependências de sistema documentadas;
3. ficheiros de configuração/credenciais fornecidos fora do Git;
4. criação/associação do tunnel no control plane;
5. ativação dos serviços systemd;
6. integração no MCP Control Center;
7. health checks e smoke tests.

## Checklist genérico

1. Instalar `git`, Python e `python3-venv` quando necessário.
2. Clonar o repositório.
3. Executar o instalador do MCP ou seguir o README respetivo.
4. Criar o runtime env a partir de `.env.example` e inserir os segredos localmente.
5. Confirmar permissões `600` nos ficheiros sensíveis.
6. Testar a fonte de dados diretamente com o health check do MCP.
7. Instalar/ativar `systemd --user`.
8. Criar ou associar um tunnel e instalar o perfil `tunnel-client`.
9. Validar `/healthz`, `/readyz` e a listagem de tools MCP.
10. Adicionar o MCP ao Control Center.
11. Só depois ligar o conector em ChatGPT.

## O que não migrar pelo Git

- passwords e tokens;
- chaves privadas;
- credenciais Google/OpenAI;
- ficheiros `.env` reais;
- dumps de produção;
- logs com PII;
- dados de clientes.
