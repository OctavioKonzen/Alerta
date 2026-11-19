#!/usr/bin/env bash
# Publica um arquivo no repositorio PUBLICO de downloads (atualizacao automatica).
#   uso: publicar.sh <pc|app> <versao> <codigo> <arquivo> <nome_publico>
# - cria a Release "<tipo>-v<versao>" com o arquivo;
# - atualiza a Release "ultima" (link fixo para baixar a versao mais nova);
# - atualiza versao-<tipo>.json, que o app e o PC leem para saber se ha versao nova.
# Precisa do segredo RELEASES_TOKEN (token com acesso de escrita ao repositorio de downloads).
set -euo pipefail
tipo="$1"; versao="$2"; codigo="$3"; arquivo="$4"; nome="$5"
repo="${DOWNLOADS_REPO:-OctavioKonzen/Alerta-downloads}"

if [ -z "${GH_TOKEN:-}" ]; then
  echo "::warning::Segredo RELEASES_TOKEN nao configurado: esta versao NAO foi publicada para atualizacao automatica."
  exit 0
fi

pasta=$(mktemp -d)
cp "$arquivo" "$pasta/$nome"
tag="$tipo-v$versao"

gh release create "$tag" "$pasta/$nome" --repo "$repo" \
  --title "$tipo $versao" --notes "Versao $versao ($tipo), gerada automaticamente." --latest=false

if ! gh release view ultima --repo "$repo" >/dev/null 2>&1; then
  gh release create ultima --repo "$repo" --title "Ultima versao" \
    --notes "Sempre a versao mais nova do app (AlertaRoblox.apk) e do PC (AlertaRoblox-Setup.exe)."
fi
gh release upload ultima "$pasta/$nome" --repo "$repo" --clobber

url="https://github.com/$repo/releases/download/$tag/$nome"
json=$(printf '{"versao":"%s","codigo":%s,"url":"%s","publicado":"%s"}' \
  "$versao" "$codigo" "$url" "$(date -u +%Y-%m-%dT%H:%M:%SZ)")
caminho="repos/$repo/contents/versao-$tipo.json"
for tentativa in 1 2 3; do
  sha=$(gh api "$caminho" --jq .sha 2>/dev/null || true)
  args=(-X PUT "$caminho" -f message="$tipo $versao" -f content="$(printf '%s' "$json" | base64 | tr -d '\n')")
  if [ -n "$sha" ]; then args+=(-f sha="$sha"); fi
  if gh api "${args[@]}" >/dev/null; then
    echo "Publicado: $url"
    exit 0
  fi
  sleep 5
done
echo "::error::Nao consegui atualizar versao-$tipo.json"
exit 1
