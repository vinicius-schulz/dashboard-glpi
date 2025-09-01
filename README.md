# GLPI Dashboard (Flask + Chart.js)
Dashboard analítico conectado ao GLPI (API REST) para visualizar e explorar chamados ligados aos grupos do usuário logado (via User Token / grupos observadores). Inclui layout personalizável, exportação com interpretação automática e autenticação opcional.

## Principais Recursos
* Série temporal: criados, resolvidos, backlog e gap cumulativo.
* Snapshot e distribuição: backlog por status, aging (faixas de idade), categoria.
* Tempo médio de resolução (horas úteis) com linha suavizada (tendência).
* Exportar / imprimir: gera documento com imagens dos gráficos + descrição + interpretação automática.
* Layout livre: arraste, redimensione, oculte widgets, salvos em `localStorage` por navegador.
* Presets de período (1 semana, mês atual, últimos 3/6 meses etc.) + granularidade Diário / Semanal / Mensal.
* Filtros de categoria (Holding vs Unimed) quando detectável pela nomenclatura.
* Ajuda contextual (botão ❔ com popover e tooltip).
* Modal detalhado de tickets ao clicar em pontos / barras / contadores.
* Auto refresh configurável (minutos) por widget de layout.
* Baseline inteligente de 6 meses para widgets “snapshot” (status, aging, abertos agora, criados hoje).
* Autenticação de usuário único opcional (ativável por variável de ambiente); logout dentro do painel ⚙️.

## Variáveis de Ambiente (.env)
Arquivo mínimo:
```env
GLPI_URL=https://sua-instancia-glpi/apirest.php
GLPI_USER_TOKEN=seu_user_token_aqui
PORT=8000                 # opcional (default 8000)
MAX_TICKETS=800           # opcional (fluxo atual não impõe limite artificial; mantido para compatibilidade)

# Autenticação (opcional)
DASHBOARD_ENABLE_AUTHENTICATION=true   # defina false/0/off para desabilitar login
DASHBOARD_ADMIN=admin                  # obrigatório se auth habilitada
DASHBOARD_PASSWORD=troca_essa_senha    # obrigatório se auth habilitada
FLASK_SECRET_KEY=uma_chave_complexa    # recomendado em produção
```
Notas:
* Se `DASHBOARD_ENABLE_AUTHENTICATION=false`, `/login` é ignorado e o dashboard abre direto.
* Sem `FLASK_SECRET_KEY`, cada restart invalida sessões (chave randômica em memória).
* `GLPI_URL` normalmente termina em `/apirest.php` — usado para montar links `/front/ticket.form.php?id=...`.
* `.env` está no `.dockerignore` — não vai para a imagem Docker.

## Executar Localmente (Python)

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

## Build e Push (opcional)

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

## Uso da Interface
| Área | Descrição |
|------|-----------|
| Header | Título do dashboard. Largura ajusta dinamicamente se o layout exceder a viewport. |
| Barra de filtros | Granularidade (Diário/Semanal/Mensal). Período por datas ou meses. Presets de intervalo (1 semana, mês atual, 3/6 meses etc.). Filtro de categoria. Atualização automática ao alterar qualquer filtro + botão Exportar/Imprimir. |
| Engrenagem (⚙️) | Abre painel de personalização (mostrar/ocultar widgets, redimensionar, auto-refresh, logout). |
| Widgets | Cartões com gráficos (Chart.js) ou números grandes (snapshot). Botão ❔ para ajuda (tooltip + popover clicável). |
| Modal de tickets | Clique em ponto/barra/contador abre lista (até 1000 tickets) com ordenação e redimensionamento de colunas. |
| Exportar/Imprimir | Gera nova janela com HTML formatado (título, meta, cada gráfico como imagem, ajuda e interpretação) e dispara `window.print()`. |

### Baseline de 6 Meses
O backend busca sempre (em paralelo) uma janela baseline de 6 meses para alimentar widgets que ignoram o filtro temporal:
* Ignoram o período: aging, backlog_status, open_today, created_today (marcados com badge / texto).
* Respeitam o período filtrado: created/resolved/gap, backlog, categoria, tempo de resolução.
Se o usuário pedir um intervalo fora dos últimos 6 meses, o backend adapta a coleta.

### Personalização de Layout
* Arraste cards (grid livre com snap de meia célula).
* Redimensione pelo canto (handle indicador).
* Oculte / mostre no painel ⚙️.
* Layout persiste em `localStorage` (`glpiDashboardLayout.v2`). Botão “Redefinir layout” limpa.

### Auto Refresh
Defina minutos no painel (0 desativa). Cada ciclo relê `/api/data` e re-renderiza.

### Exportação & Interpretação
Botão “Exportar / Imprimir”: converte cada gráfico para base64 (Chart.js) + bloco “Interpretação” heurística e ajuda do widget.

### Logout
Disponível dentro do painel ⚙️ (link “Sair”). Só aparece se `DASHBOARD_ENABLE_AUTHENTICATION=true`.

## Segurança & Boas Práticas
* Defina `FLASK_SECRET_KEY` em produção.
* Use HTTPS para proteger credenciais de login (se auth habilitada).
* Restrinja acesso de rede se `DASHBOARD_ENABLE_AUTHENTICATION` estiver desativada.
* Tokens GLPI nunca devem ser expostos no navegador ou incluídos em imagens Docker públicas.

## Estrutura Simplificada do Fluxo
1. Front-end solicita `/api/data` com parâmetros (granularidade, período, categoria).
2. Backend coleta dados (janela filtrada + baseline 6 meses), processa métricas e devolve JSON.
3. Front-end monta ou atualiza gráficos (Chart.js) e armazena última resposta para uso em exportação / insights.
4. Interações (cliques) solicitam `/api/tickets` com contexto (source, label, período) e exibem modal.

## Roadmap / Possíveis Extensões
* PDF server-side (WeasyPrint / wkhtmltopdf) para exportação mais fiel.
* Filtros adicionais (grupo específico, status múltiplos, SLA breaches).
* Modo multiusuário / RBAC.
* Dashboards salvos nomeados.

## Notas
* `.env` não vai para a imagem Docker — use `--env-file`.
* Fluxo legado baseado em `Group_Ticket` foi substituído por busca otimizada em “Grupo observador”.
* Ajustes de layout e preferências são por navegador (não sincronizados).

## CI / GitHub Actions (runner self-hosted)

Este repositório inclui um workflow de exemplo para build/push e deploy em Kubernetes usando um runner self-hosted que pode rodar dentro do próprio cluster.

Resumo rápido:
- Instale/registre um runner dentro do cluster (manifests em `k8s/prd/02-runner-secret.yaml`, `03-runner-rbac.yaml`, `04-runner-deployment.yaml`).
- Crie um Secret do tipo docker-registry chamado `ghcr-secret` se usar a imagem oficial do runner em `ghcr.io`.
- Configure os Secrets e Repository Variables no GitHub (veja lista abaixo).
- Faça commit na `main` para disparar o workflow `.github/workflows/k8s-deploy.yml`.

Secrets necessários (Repository → Settings → Secrets → Actions):
- `DASHBOARD_ADMIN`
- `DASHBOARD_PASSWORD`
- `DOCKERHUB_TOKEN` (para push no Docker Hub)
- `GLPI_USER_TOKEN`

Repository Variables recomendadas (Settings → Variables):
- `DOCKERHUB_USERNAME`
- `IMAGE_REPOSITORY` (opcional)
- `DASHBOARD_ENABLE_AUTHENTICATION`
- `GLPI_URL`
- `DEBUG_SEARCH_OPTIONS`
- `URL_DASHBOARD`

Criar o Secret para pull do GHCR (exemplo, NÃO comite esse token):
```bash
GH_USER="seu-usuario-github"
GH_TOKEN="seu_pat_com_read:packages"
kubectl create secret docker-registry ghcr-secret \
  --docker-server=ghcr.io \
  --docker-username="$GH_USER" \
  --docker-password="$GH_TOKEN" \
  -n default
```

Gerar token de registro do runner (válido por poucos minutos):
- Pela UI: GitHub → Settings → Actions → Runners → New self-hosted runner (gera token temporário)

Aplicar os manifests do runner:
```bash
kubectl apply -f k8s/prd/02-runner-secret.yaml
kubectl apply -f k8s/prd/03-runner-rbac.yaml
kubectl apply -f k8s/prd/04-runner-deployment.yaml
kubectl -n default rollout restart deployment/github-runner
kubectl -n default rollout status deployment/github-runner --timeout=120s
```

Workflow de deploy: `.github/workflows/k8s-deploy.yml` — ele realiza build/push da imagem (Docker Hub), substitui placeholders em `k8s/prd/*` e aplica `k8s/prd/output` no cluster.

Boas práticas rápidas:
- Não comite tokens nem `.dockerconfigjson` no repo.
- Em produção, considere Actions Runner Controller (ARC) para runners efêmeros e registro via GitHub App.
- Use SealedSecrets / ExternalSecrets / Vault para gerenciar secrets no cluster.
