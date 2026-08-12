#!/usr/bin/env bash
set -euo pipefail

# Run on the server after DNS A records point to this host.
certbot --nginx \
  -d uhbse.tech \
  -d www.uhbse.tech \
  --non-interactive \
  --agree-tos \
  --register-unsafely-without-email \
  --redirect

systemctl reload nginx
echo "SSL enabled for uhbse.tech"
