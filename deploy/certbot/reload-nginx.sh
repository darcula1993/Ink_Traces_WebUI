#!/bin/sh
set -eu

if systemctl is-active --quiet nginx; then
    systemctl reload nginx
fi
