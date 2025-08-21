# icalendar-vevent
# GLPI Dashboards com Python

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
