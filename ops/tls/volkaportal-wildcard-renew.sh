#!/bin/sh
set -eu

key_file=/etc/volkaportal/spaceship-api-key
secret_file=/etc/volkaportal/spaceship-api-secret

if [ ! -s "$key_file" ] || [ ! -s "$secret_file" ]; then
    echo "Spaceship DNS credentials are missing" >&2
    exit 1
fi

umask 077
export SPACESHIP_API_KEY_FILE="$key_file"
export SPACESHIP_API_SECRET_FILE="$secret_file"

cert_dir=/var/lib/volkaportal/lego/certificates
cert=$cert_dir/volkaportal.com.crt
key=$cert_dir/volkaportal.com.key
if [ ! -s "$cert" ] || [ ! -s "$key" ]; then
    echo "Wildcard TLS must be bootstrapped before enabling renewal" >&2
    exit 1
fi

backup_dir=$(mktemp -d /var/lib/volkaportal/lego/renew-backup.XXXXXX)
cp -p "$cert" "$backup_dir/cert.crt"
cp -p "$key" "$backup_dir/cert.key"

finish() {
    status=$?
    trap - 0
    if [ "$status" -ne 0 ]; then
        cp -p "$backup_dir/cert.crt" "$cert"
        cp -p "$backup_dir/cert.key" "$key"
        if nginx -t; then
            systemctl reload nginx
        fi
    fi
    rm -rf "$backup_dir"
    exit "$status"
}
trap finish 0

/usr/local/bin/lego run \
    --path /var/lib/volkaportal/lego \
    --server letsencrypt \
    --email info@volkaportal.com \
    --accept-tos \
    --dns spaceship \
    --domains volkaportal.com \
    --domains '*.volkaportal.com' \
    --deploy-hook /usr/local/libexec/volkaportal/validate-and-reload-tls.sh
