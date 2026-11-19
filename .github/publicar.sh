#!/usr/bin/env bash
# Publica um arquivo na Release fixa "ultima" deste repositorio (que e publico),
# para os jogadores baixarem e para a atualizacao automatica.
#   uso: publicar.sh <pc|app> <versao> <codigo> <arquivo> <nome_publico>
# Envia primeiro o arquivo e depois o versao-<tipo>.json (o app e o PC leem
# esse json para saber se ha versao nova).
set -euo pipefail
tipo="$1"; versao="$2"; codigo="$3"; arquivo="$4"; nome="$5"
repo="${GITHUB_REPOSITORY:-OctavioKonzen/Alerta}"
base="https://github.com/$repo/releases/download/ultima"

if ! gh release view ultima --repo "$repo" >/dev/null 2>&1; then
  # (se o outro build criar ao mesmo tempo, tudo bem)
  gh release create ultima --repo "$repo" --title "Ultima versao" --latest \
    --notes "Baixe aqui: AlertaRoblox.apk (celular Android) e AlertaRoblox-Setup.exe (PC Windows). Depois de instalados, eles se atualizam sozinhos." \
    || sleep 5
  gh release view ultima --repo "$repo" >/dev/null
fi

pasta=$(mktemp -d)
cp "$arquivo" "$pasta/$nome"
printf '{"versao":"%s","codigo":%s,"url":"%s/%s","publicado":"%s"}\n' \
  "$versao" "$codigo" "$base" "$nome" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$pasta/versao-$tipo.json"

gh release upload ultima "$pasta/$nome" --repo "$repo" --clobber
gh release upload ultima "$pasta/versao-$tipo.json" --repo "$repo" --clobber
echo "Publicado: $base/$nome (versao $versao)"
