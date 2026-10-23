#!/bin/sh
set -eu

cert=${LEGO_HOOK_CERT_PATH:?certificate path is missing}
key=${LEGO_HOOK_CERT_KEY_PATH:?certificate key path is missing}
site=/etc/nginx/sites-enabled/aksiyon-takip
expected_cert=/var/lib/volkaportal/lego/certificates/volkaportal.com.crt
expected_key=/var/lib/volkaportal/lego/certificates/volkaportal.com.key

test -s "$cert"
test -s "$key"
test "$(realpath "$cert")" = "$expected_cert"
test "$(realpath "$key")" = "$expected_key"
openssl x509 -in "$cert" -noout -checkend 604800 >/dev/null
test "$(grep -c -- '-----BEGIN CERTIFICATE-----' "$cert")" -ge 2
openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt -untrusted "$cert" "$cert" >/dev/null
san_names=$(openssl x509 -in "$cert" -noout -ext subjectAltName | tr ',' '\n' | sed -n 's/^[[:space:]]*DNS://p')
printf '%s\n' "$san_names" | grep -Fx 'volkaportal.com' >/dev/null
printf '%s\n' "$san_names" | grep -Fx '*.volkaportal.com' >/dev/null

cert_key=$(openssl x509 -in "$cert" -noout -pubkey | openssl pkey -pubin -outform DER | sha256sum | cut -d ' ' -f 1)
private_key=$(openssl pkey -in "$key" -pubout -outform DER | sha256sum | cut -d ' ' -f 1)
test "$cert_key" = "$private_key"

awk -v path="$expected_cert;" '$1 == "ssl_certificate" && $2 == path { found = 1 } END { exit !found }' "$site"
awk -v path="$expected_key;" '$1 == "ssl_certificate_key" && $2 == path { found = 1 } END { exit !found }' "$site"
nginx -t
systemctl reload nginx

expected_fingerprint=$(openssl x509 -in "$cert" -noout -fingerprint -sha256)
for hostname in ceo.volkaportal.com tls-probe.volkaportal.com; do
    served_chain=$(timeout 10 openssl s_client \
        -connect 127.0.0.1:443 \
        -servername "$hostname" \
        -verify_hostname "$hostname" \
        -verify_return_error </dev/null 2>&1)
    served_fingerprint=$(printf '%s\n' "$served_chain" | openssl x509 -noout -fingerprint -sha256)
    test "$expected_fingerprint" = "$served_fingerprint"
done
