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
GLPI_GROUP_IDS=12,34,56
```



- GLPI_URL: URL base da API REST do GLPI (normalmente termina com /apirest.php)
- GLPI_USER_TOKEN: Token pessoal gerado nas preferências do seu usuário no GLPI
- GLPI_GROUP_IDS: Lista de IDs dos grupos que você quer monitorar, separados por vírgula

### 5. Executar a aplicação

Use o Streamlit para rodar a UI:

```bash
streamlit run app.py
```

Se preferir, defina variáveis em `.env`:

```
GLPI_URL=https://sua-instancia-glpi/apirest.php
GLPI_USER_TOKEN=seu_user_token_aqui
# opcional
MAX_TICKETS=800
```

Observação: os grupos do usuário são lidos automaticamente via `getFullSession (session.glpigroups)`.
