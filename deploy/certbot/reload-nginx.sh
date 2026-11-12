#!/bin/sh
set -eu

if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet nginx; then
    systemctl reload nginx
elif command -v nginx >/dev/null 2>&1; then
    nginx -s reload
fi
