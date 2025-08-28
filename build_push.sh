#!/usr/bin/env bash

# build_push.sh - Script auxiliar para build e push da imagem Docker do dashboard GLPI.
#
# Requisitos:
#   - Docker instalado e em execução
#   - Já ter feito: docker login (antes de rodar este script)
#   - (Opcional) arquivo .env com variáveis para testar container localmente (não é copiado para a imagem)
#
# Uso básico:
#   ./build_push.sh -u <dockerhub_user> -i dashboard-glpi -v 1.0.0
#
# Parâmetros:
#   -u|--user       (OBRIG.) Nome de usuário/organização no Docker Hub
#   -i|--image      (OPC.)  Nome do repositório (padrão: dashboard-glpi)
#   -v|--version    (OPC.)  Tag de versão (default: auto = YYYY.MM.DD+gitSHA curto)
#   -p|--platforms  (OPC.)  Plataformas para build multi-arquitetura (ex: linux/amd64,linux/arm64)
#   --no-cache      (OPC.)  Faz build sem cache
#   --no-push       (OPC.)  Apenas build local (não envia para o registry)
#   --dry-run       (OPC.)  Mostra comandos sem executar
#   -f|--dockerfile (OPC.)  Caminho do Dockerfile (default: Dockerfile)
#   -h|--help       Mostra ajuda
#
# Exemplos:
#   ./build_push.sh -u meuuser -v 1.0.0
#   ./build_push.sh -u meuuser -p linux/amd64,linux/arm64 -v 2025.08.25
#   ./build_push.sh -u orgxyz --no-push   # só build local
#
set -euo pipefail

COLOR_BLUE="\033[34m"
COLOR_GREEN="\033[32m"
COLOR_YELLOW="\033[33m"
COLOR_RED="\033[31m"
COLOR_RESET="\033[0m"

log() { echo -e "${COLOR_BLUE}[INFO]${COLOR_RESET} $*"; }
warn() { echo -e "${COLOR_YELLOW}[WARN]${COLOR_RESET} $*"; }
err() { echo -e "${COLOR_RED}[ERRO]${COLOR_RESET} $*" >&2; }
succ() { echo -e "${COLOR_GREEN}[OK]${COLOR_RESET} $*"; }

USER_NAME="viniciusschulz"
IMAGE_NAME="dashboard-glpi" 
VERSION="1.0.13"
PLATFORMS=""
NO_CACHE=0
NO_PUSH=0
DRY_RUN=0
DOCKERFILE="Dockerfile"

usage() {
  grep '^#' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

run_cmd() {
  local cmd="$1"
  if [[ "$DRY_RUN" == 1 ]]; then
    echo "[dry-run] $cmd"
  else
    eval "$cmd"
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -u|--user) USER_NAME="$2"; shift 2;;
    -i|--image) IMAGE_NAME="$2"; shift 2;;
    -v|--version) VERSION="$2"; shift 2;;
    -p|--platforms) PLATFORMS="$2"; shift 2;;
    --no-cache) NO_CACHE=1; shift;;
    --no-push) NO_PUSH=1; shift;;
    --dry-run) DRY_RUN=1; shift;;
    -f|--dockerfile) DOCKERFILE="$2"; shift 2;;
    -h|--help) usage;;
    *) err "Parâmetro desconhecido: $1"; usage;;
  esac
done

if [[ -z "$USER_NAME" ]]; then
  err "--user é obrigatório"
  usage
fi

# Gerar versão default se não fornecida
if [[ -z "$VERSION" ]]; then
  DATE_TAG=$(date +%Y.%m.%d)
  GIT_SHA=""
  if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
    GIT_SHA=$(git rev-parse --short HEAD || echo "nogit")
  else
    GIT_SHA="nogit"
  fi
  VERSION="${DATE_TAG}-${GIT_SHA}"
  warn "Tag de versão não informada. Usando versão gerada: $VERSION"
fi

FULL_IMAGE="$USER_NAME/$IMAGE_NAME"

log "Imagem alvo: $FULL_IMAGE"
log "Versão: $VERSION"
[[ -n "$PLATFORMS" ]] && log "Plataformas: $PLATFORMS" || log "Plataformas: (single build local)"
[[ $NO_CACHE == 1 ]] && log "Build sem cache" || true
[[ $NO_PUSH == 1 ]] && log "Sem push (no-push)" || true
[[ $DRY_RUN == 1 ]] && log "Modo dry-run (não executa comandos)" || true

if [[ ! -f "$DOCKERFILE" ]]; then
  err "Dockerfile não encontrado em: $DOCKERFILE"
  exit 1
fi

# Verificação simples de login (não falha se offline)
if [[ $DRY_RUN == 0 && $NO_PUSH == 0 ]]; then
  if ! docker info 2>/dev/null | grep -qi 'Username:'; then
    warn "Parece que você não está logado no Docker Hub. Rode: docker login"
  fi
fi

BUILD_OPTS="-f $DOCKERFILE"
[[ $NO_CACHE == 1 ]] && BUILD_OPTS+=" --no-cache"

if [[ -n "$PLATFORMS" ]]; then
  # Build multi-arch (necessita docker buildx; assume builder default configurado)
  log "Iniciando build multi-arch"
  CMD="docker buildx build $BUILD_OPTS --platform $PLATFORMS -t $FULL_IMAGE:$VERSION -t $FULL_IMAGE:latest ."
  if [[ $NO_PUSH == 1 ]]; then
    CMD+=" --load"  # carrega para o daemon local
    run_cmd "$CMD"
  else
    CMD+=" --push"
    run_cmd "$CMD"
  fi
else
  # Build simples
  log "Iniciando build local (single arch)"
  run_cmd "docker build $BUILD_OPTS -t $FULL_IMAGE:$VERSION -t $FULL_IMAGE:latest ."
  if [[ $NO_PUSH == 0 ]]; then
    log "Fazendo push das tags"
    run_cmd "docker push $FULL_IMAGE:$VERSION"
    run_cmd "docker push $FULL_IMAGE:latest"
  fi
fi

succ "Build concluído."; [[ $NO_PUSH == 0 ]] && succ "Push concluído." || warn "Push omitido (--no-push)."

echo
echo "Teste local (opcional):"
echo "  docker run --rm -p 8000:8000 --env-file .env $FULL_IMAGE:$VERSION"
echo
echo "Imagem(s) disponíveis:"
echo "  $FULL_IMAGE:$VERSION"
echo "  $FULL_IMAGE:latest"
