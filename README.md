# GLPI Dashboards com Python
Este projeto conecta-se ao GLPI via API REST para consultar chamados atribuídos ao(s) grupo(s) de um usuário e gerar dashboards/indicadores.

## Pré-requisitos

- Python 3.10+ (para execução local) ou Docker (para execução em contêiner)
- Acesso ao GLPI com um **User Token** válido
- Permissões de leitura de chamados no GLPI

## Variáveis de ambiente (.env)

Crie um arquivo `.env` na raiz do projeto com ao menos estas variáveis:

```text
GLPI_URL=https://sua-instancia-glpi/apirest.php
GLPI_USER_TOKEN=seu_user_token_aqui
# opcional
PORT=8000
MAX_TICKETS=800
```

Adicionalmente, o dashboard suporta uma autenticação simples (usuário único) controlada por variáveis de ambiente:

```text
# Habilita/desabilita a exigência de login (true/false). Se 'false', o dashboard abre direto sem pedir credenciais.
DASHBOARD_ENABLE_AUTHENTICATION=true
# Usuário e senha (apenas necessários se a autenticação estiver habilitada)
DASHBOARD_ADMIN=admin
DASHBOARD_PASSWORD=troca_essa_senha
# opcional: chave secreta do Flask para sessões
FLASK_SECRET_KEY=uma_chave_complexa
```

Notas:
- Quando `DASHBOARD_ENABLE_AUTHENTICATION` estiver definida como `false` (ou 0/No/Off), o sistema não exigirá login e qualquer pessoa que acesse a URL terá acesso ao dashboard.
- Se a autenticação estiver habilitada, defina `DASHBOARD_ADMIN` e `DASHBOARD_PASSWORD`. O usuário usa a tela de `/login` para entrar.
- `FLASK_SECRET_KEY` é recomendada em produção para garantir a integridade das sessões; se não informada, uma chave aleatória será gerada a cada start (invalida sessions entre reinícios).

Observações:
- `GLPI_URL` normalmente termina com `/apirest.php`.
- O arquivo `.env` está no `.dockerignore` por segurança e **não** é copiado para a imagem.

## Executar localmente (Python)

1. Criar e ativar um ambiente virtual (opcional):

```bash
python -m venv venv
# Linux / macOS
source venv/bin/activate
# Windows PowerShell
venv\Scripts\Activate.ps1
```

2. Instalar dependências e iniciar o servidor:

```bash
pip install -r requirements.txt
python server.py
```

3. Acesse: http://localhost:8000 (usa `PORT` do `.env` ou 8000 por padrão)

## Executar com Docker (pull + run)

Se a imagem já estiver publicada no Docker Hub, puxe e execute usando `--env-file` para injetar variáveis no tempo de execução:

### PowerShell

```powershell
# Puxar imagem
docker pull viniciusschulz/dashboard-glpi:latest

# Rodar com .env mapeado (porta 8000 por padrão)
docker run --rm -p 8000:8000 --env-file .env viniciusschulz/dashboard-glpi:latest
```

### Bash / WSL / Linux

```bash
# Pull
docker pull viniciusschulz/dashboard-glpi:latest
# Run
docker run --rm -p 8000:8000 --env-file .env viniciusschulz/dashboard-glpi:latest
```

Dicas:
- Use `-e VAR=value` para sobrescrever variáveis individualmente.
- Use tags imutáveis (ex: `viniciusschulz/dashboard-glpi:2025.08.25-abc`) em vez de `:latest` para rastreabilidade.

## Build e push (opcional)

O repositório inclui `build_push.sh` para automatizar build/push no Docker Hub.

Exemplos:

```bash
./build_push.sh -u SEU_USUARIO -v 1.0.0           # build + push
./build_push.sh -u SEU_USUARIO -p linux/amd64,linux/arm64 -v 2025.08.25  # multi-arch
./build_push.sh -u SEU_USUARIO --no-push         # apenas build local
```

Comandos manuais:

```bash
docker build -t SEU_USUARIO/dashboard-glpi:1.0.0 .
docker push SEU_USUARIO/dashboard-glpi:1.0.0
```

## Notas

- O `.env` não é copiado para a imagem (veja `.dockerignore`). Passe credenciais em runtime com `--env-file` ou `-e`.
- Para desenvolvimento, rode localmente com Python; use Docker para implantação/produção.
- Posso adicionar um `docker-compose.yml` se quiser orquestrar o serviço com variáveis e volumes.

Este projeto conecta-se ao GLPI via API REST para consultar chamados atribuídos ao(s) grupo(s) de um usuário e gerar dashboards/indicadores.

## Pré-requisitos

- Python 3.10+ instalado
- Acesso ao GLPI com um **User Token** válido
- Permissões de leitura de chamados no GLPI

## Passos para execução

### 1. Clonar o repositório

```bash
git clone https://seu-repositorio.git
cd glpi-dash
```

### 2. Criar ambiente virtual (opcional, mas recomendado)
```bash
python3 -m venv venv
source venv/bin/activate   # Linux/Mac
venv\Scripts\activate      # Windows PowerShell
```

### 3. Instalar dependências
```bash
pip install -r requirements.txt
```

### 4. Criar o arquivo .env

- Crie um arquivo chamado .env na raiz do projeto com o seguinte conteúdo:

```bash
GLPI_URL=https://sua-instancia-glpi/apirest.php
GLPI_USER_TOKEN=seu_user_token_aqui
```



- GLPI_URL: URL base da API REST do GLPI (normalmente termina com /apirest.php)
- GLPI_USER_TOKEN: Token pessoal gerado nas preferências do seu usuário no GLPI

### 5. Executar a aplicação (Flask + HTML)

A nova versão usa um servidor Flask (API JSON) com front-end HTML/Chart.js.

1) Configure variáveis no arquivo `.env` (raiz do projeto):

```
GLPI_URL=https://sua-instancia-glpi/apirest.php
GLPI_USER_TOKEN=seu_user_token_aqui
# opcional
MAX_TICKETS=800
PORT=8000
```

2) Instale dependências e inicie o servidor Flask:

```bash
pip install -r requirements.txt
python server.py
```

3) Acesse no navegador: http://localhost:8000

Observações:
- Os grupos do usuário são lidos automaticamente via `getFullSession (session.glpigroups)`.
- A UI permite ajustar granularidade (Diário/Semanal), período e limite de tickets.
 - Nota: o fluxo legado baseado em Group_Ticket foi removido; a coleta usa busca direta em
	 search/Ticket pelo campo "Grupo observador" para melhor performance.
