#!/usr/bin/env bash
set -euo pipefail

INDEXNOW_KEY="uhbse7c4a9f2e8b1d6"
HOST="uhbse.tech"

URLS=(
  "https://${HOST}/"
  "https://${HOST}/?lang=ru"
  "https://${HOST}/?lang=ar"
  "https://${HOST}/?lang=zh"
  "https://${HOST}/?lang=es"
  "https://${HOST}/?lang=fr"
  "https://${HOST}/?lang=de"
)

json_urls="$(printf '"%s",' "${URLS[@]}")"
json_urls="[${json_urls%,}]"

payload="$(cat <<EOF
{
  "host": "${HOST}",
  "key": "${INDEXNOW_KEY}",
  "keyLocation": "https://${HOST}/${INDEXNOW_KEY}.txt",
  "urlList": ${json_urls}
}
EOF
)"

echo "Submitting ${#URLS[@]} URLs to IndexNow..."
curl -fsS "https://api.indexnow.org/indexnow" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d "${payload}" \
  && echo "IndexNow: accepted" \
  || echo "IndexNow: request failed (non-fatal)"

curl -fsS "https://yandex.com/indexnow" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d "${payload}" \
  && echo "Yandex IndexNow: accepted" \
  || echo "Yandex IndexNow: request failed (non-fatal)"
