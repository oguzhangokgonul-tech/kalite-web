# VolkaPortal wildcard DNS/TLS rollout

## Current production state (2026-10-23)

- `ceo.volkaportal.com` A record resolves to `94.103.45.122` and HTTPS `/login` returns 200 with company code `003`.
- `volkaportal.com`, `erprefabrik.volkaportal.com` and `sagiroglucelik.volkaportal.com` continue to serve valid HTTPS.
- Live Nginx file: `/etc/nginx/sites-enabled/aksiyon-takip`. The `ceo` name was added to its HTTP and HTTPS `server_name` lists; all proxy settings were preserved.
- Existing Certbot lineage `volkaportal.com` now covers apex, `ceo`, `erprefabrik`, and `sagiroglucelik`. It expires 2027-01-21. The old `www` name was excluded because public DNS returned NXDOMAIN.
- `certbot renew --dry-run` succeeded for both existing lineages.
- Root-only Nginx/Let's Encrypt backup: `/root/volkaportal-tls-20261023/nginx-letsencrypt-before.tar.gz`.
- Verified `lego` v5.5.2 binary is staged at `/usr/local/bin/lego`. The Spaceship DNS helper and systemd units are staged, but the wildcard timer is **disabled** until credentials, DNS, TLS and tenant-host checks pass.
- The tenant-host guard and cross-field company-domain collision checks are deployed at commit `5594a77`. A verified full backup was taken before deployment. Known tenant HTTPS smoke checks passed, and an unregistered tenant host returns 404 at the application layer.
- Spaceship API credential files are still missing. Wildcard DNS and certificate issuance have **not** been performed; automatic onboarding of future tenant domains is not yet active.

## Remaining cutover

1. Create a Spaceship API key with only `dnsrecords:read` and `dnsrecords:write`; store key and secret in root-owned mode-0600 files at `/etc/volkaportal/spaceship-api-key` and `/etc/volkaportal/spaceship-api-secret`. Never put either value in Git, shell arguments or logs.
2. Recheck the deployed application host guard: an unknown `*.volkaportal.com` host must reject requests even with a valid tenant session cookie. Check company-domain collisions at creation/edit time. `www.volkaportal.com` intentionally maps to the platform apex.
3. Run `ops/tls/spaceship_wildcard_dns.py` without `--apply` to inspect the zone. Do not publish the wildcard A record until a wildcard certificate is serving; otherwise new hosts may temporarily reach the server with a mismatched certificate.
4. Bootstrap once with the root-only Spaceship credential files, without the deploy hook. Use the same path, ACME server, email and domain set as the renewal wrapper:

   ```sh
   export SPACESHIP_API_KEY_FILE=/etc/volkaportal/spaceship-api-key
   export SPACESHIP_API_SECRET_FILE=/etc/volkaportal/spaceship-api-secret
   umask 077
   /usr/local/bin/lego run --path /var/lib/volkaportal/lego --server letsencrypt \
     --email info@volkaportal.com --accept-tos --dns spaceship \
     --domains volkaportal.com --domains '*.volkaportal.com'
   ```

   Verify the issued certificate contains both `volkaportal.com` and `*.volkaportal.com` and that `.crt` contains the chain. The installed renewal wrapper adds a deploy hook and is intended for use after Nginx points at the lego files.
5. Back up Nginx again. Replace the VolkaPortal HTTPS certificate paths with the issued `lego` certificate/key paths; add `*.volkaportal.com` to HTTP and HTTPS `server_name`. Preserve the redirect domain, `Host $host`, static include and TLS options. Run `nginx -t`, then reload. Test the wildcard certificate using a forced host-to-IP connection before changing DNS.
6. Run the DNS helper with `--apply` and confirm an authoritative wildcard A response. Existing exact A records must be retained. Externally check apex, all current tenants, `ceo`, `www` and one unknown host. Known hosts must have valid TLS and correct tenant selection; the unknown host must never show tenant data. Enable and test `volkaportal-wildcard.timer` only after these checks.
7. Inspect renewal logs and certificate expiry monitoring. The renewal wrapper snapshots the currently serving certificate and key and restores them if lego or the post-reload check fails. The existing Certbot lineage remains available for cutover rollback; do not delete it.

## Rollback

Restore the saved Nginx file or old certificate paths, validate with `nginx -t`, then reload Nginx and repeat HTTPS checks. Disable the wildcard timer if its renewal fails. Keep the previously working explicit DNS records and Certbot certificate. No database migration is part of this DNS/TLS change.
