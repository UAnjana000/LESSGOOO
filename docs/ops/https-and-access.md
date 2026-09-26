# HTTPS, certificates and the visitor/staff boundary [PROD]

The edge proxy (`deploy/production/caddy/Caddyfile`) terminates TLS for two sites:

| Site | Container port | Default host port | Certificate files |
| --- | --- | --- | --- |
| `VISITOR_SITE` (gallery) | 443, with 80 redirecting to HTTPS | `VISITOR_BIND_IP:443` / `:80` | `certs/visitor.crt`, `certs/visitor.key` |
| `STAFF_SITE` (staff) | 8443 | `STAFF_BIND_IP:8443` | `certs/staff.crt`, `certs/staff.key` |

The service worker and the offline exhibit cache need a secure origin, and the kiosks must trust the certificate. Each certificate's SAN must contain its site's hostname, and clients must use that hostname, not an IP address.

## Getting certificates

Choose one option per site and record the choice.

1. **Public certificate for an institution subdomain (recommended for Android kiosks).** Use names such as `archive.gallery.<institution domain>` resolved to the LAN IPs by internal (split) DNS. Obtain the certificate with the DNS-01 challenge; on Windows, win-acme can do DNS validation and export PEM files. Place the full chain in `visitor.crt` and the key in `visitor.key`. No CA installation on kiosks is needed. Automate renewal, then run `docker compose --env-file .env -f compose.yaml restart proxy`. The proxy runs with its admin API off, so it cannot hot-reload.
2. **Institution internal CA.** Issue certificates for both hostnames and install the CA root on every kiosk, display and staff machine. On Android: Settings > Security > Encryption & credentials > Install a certificate > CA certificate; with MDM in production. Chrome on Android honours user-installed CAs; other apps may not.
3. **ACME from the proxy.** Set `VISITOR_TLS=<contact email>`. This works only if the server is reachable from the internet on ports 80 and 443 for the hostname, which a gallery LAN normally is not.

`VISITOR_TLS=internal` and `STAFF_TLS=internal` use Caddy's own CA. They are for staging rehearsals only; the preflight check fails on them.

`VISITOR_TLS` and `STAFF_TLS` are passed verbatim to Caddy's `tls` directive. The default is `/certs/<site>.crt /certs/<site>.key`, read from `CERTS_PATH`.

**Expiry.** Track certificate expiry in the monitoring checklist ([health-and-logs.md](health-and-logs.md)). To check the served certificate:

```powershell
curl.exe -svI https://<VISITOR_SITE>/ 2>&1 | Select-String 'expire date|subject:'
```

## Network boundary

The boundary has three layers, strongest first:

1. **Network.** Gallery devices sit on an isolated VLAN with no route to the staff network (spec 9). Switch ACLs allow gallery clients only to `VISITOR_BIND_IP:80,443`.
2. **Host.** The two listeners are separate container ports bound to separate interfaces (`VISITOR_BIND_IP`, `STAFF_BIND_IP`). Scope them with Windows Firewall as well.

   ```powershell
   # Adjust subnets. Block rules override any allow rule Docker Desktop adds for its backend.
   New-NetFirewallRule -DisplayName 'Archive staff HTTPS - block gallery VLAN' -Direction Inbound -Protocol TCP -LocalPort 8443 -RemoteAddress 10.10.10.0/24 -Action Block
   New-NetFirewallRule -DisplayName 'Archive staff HTTPS - staff VLAN' -Direction Inbound -Protocol TCP -LocalPort 8443 -RemoteAddress 10.20.20.0/24 -Action Allow
   New-NetFirewallRule -DisplayName 'Archive visitor HTTPS - gallery VLAN' -Direction Inbound -Protocol TCP -LocalPort 80,443 -RemoteAddress 10.10.10.0/24,10.20.20.0/24 -Action Allow
   ```

3. **Proxy routing.** The gallery listener routes only `/api/visitor/*`, `/iiif/*` and `/api/health` to the api. Every other `/api/*` path returns 404, `/staff` redirects to `/`, and request bodies are capped at 64 KB. The api also requires a staff JWT on every staff route.

**Egress.** Allow outbound HTTPS from the server only to the Sarvam, LLM and Langfuse endpoints actually configured (spec 9). Docker does not filter by destination.

### `STAFF_ALLOWED_CIDRS` and Docker Desktop

The staff site can also check source IPs (`STAFF_ALLOWED_CIDRS`). With Docker Desktop's port forwarding, the proxy sees every client as the Docker gateway address. The smoke test logged `remote_ip=172.22.0.1` for a localhost client, so this check cannot tell staff from gallery clients there. Leave it at `private_ranges` and rely on layers 1 and 2. On a Linux host, or wherever the proxy access log shows real client addresses, set it to the staff subnet.

## Verifying the boundary

Run these from a gallery-network machine, or from the server with `--resolve`:

```powershell
$v = 'archive.gallery.example.org'      # VISITOR_SITE
$s = 'staff.archive.example.org'        # STAFF_SITE
curl.exe -s -o NUL -w '%{http_code}  PWA`n'              "https://$v/"
curl.exe -s -o NUL -w '%{http_code}  visitor API`n'      "https://$v/api/visitor/config"
curl.exe -s -o NUL -w '%{http_code}  staff API (404)`n'  "https://$v/api/staff/stats"
curl.exe -s -o NUL -w '%{http_code}  readiness (404)`n'  "https://$v/api/health/ready"
curl.exe -s -o NUL -w '%{http_code}  staff site from gallery (must not connect)`n' --connect-timeout 5 "https://${s}:8443/"
```

Smoke-test results (localhost, test certificate):

| Check | Result |
| --- | --- |
| Gallery listener serves the PWA and the SPA deep link `/timeline` | 200 |
| `/api/visitor/config` on gallery | 200 |
| `/api/health` on gallery | 200 |
| `/api/staff/login` and `/api/staff/stats` on gallery | 404 |
| `/api/health/ready` and `/api/docs` on gallery | 404 |
| `/staff/review` on gallery | 302 to `/` |
| Staff hostname or forged `Host` header on the gallery port | Empty response, nothing proxied |
| 70 KB body to `/api/visitor/ask` | 413 |
| `/api/staff/stats` on staff without a token | 401 |
| `/api/health/ready` on staff | 200 |
| HTTP on the gallery port | 301 to HTTPS |
| Security headers | HSTS, CSP, `nosniff`; `Server` header removed |

## Not configured (production gaps)

- **Rate limiting** (spec 6.5) is not part of stock Caddy. It needs a custom Caddy build with a rate-limit module, or an upstream firewall or proxy.
- **Kiosk device identity** (spec 6.5) could use mutual TLS on the gallery site (Caddy `client_auth`) with device certificates issued through MDM. It is not enabled, because it needs a device PKI.
- **SSO/MFA** for staff (spec 6.5 and 9) is an application change.
