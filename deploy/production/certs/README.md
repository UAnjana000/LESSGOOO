# deploy/production/certs

PEM certificates and keys for the edge proxy, mounted read-only at `/certs`. Everything here except this README is git-ignored.

| File | Site |
| --- | --- |
| `visitor.crt`, `visitor.key` | `VISITOR_SITE` (gallery network) |
| `staff.crt`, `staff.key` | `STAFF_SITE` (staff network) |

The `.crt` file holds the full chain (leaf first). Keys are unencrypted PEM, readable only by the account that runs Docker. After replacing a certificate, run `docker compose --env-file .env -f compose.yaml restart proxy`. The proxy runs with its admin API off, so it cannot hot-reload.

See `docs/ops/https-and-access.md` for where certificates come from and how kiosks trust them.
