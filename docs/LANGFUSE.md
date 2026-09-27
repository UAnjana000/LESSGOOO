# Self-hosted Langfuse (redacted AI traces)

Status on 2026-09-27 at 12:32 IST: self-hosted Langfuse 4.46.0 is running beside the local demo. One real Ask went through the archive's own tracing code, and its redacted trace was read back from Langfuse's API. That trace carried token usage, cost, latency, model and prompt version, and none of the checked visitor data, secrets or archive text. The running `api` and `worker` containers have **not** been recreated yet, so live visitor Asks still go to the local JSONL sink until the step in "Apply to the running stack" is done.

Spec basis: §4.9 (Langfuse holds traces, token usage, latency, failures and prompt versions; it is not archive storage or the audit history), §6.6 (self-hosted; redaction), §7.1 (edge server or a separate machine), §3.4 (move Langfuse off the edge server if the benchmark shows no headroom).

## Topology

```
host (127.0.0.1 only)
  :3100 ─────────────► langfuse-web ─┐           compose project "ambedkar-langfuse"
                          ▲          │ network "internal" (internal: true, no egress)
                          │          ├─ langfuse-worker
  core project            │          ├─ postgres    (Langfuse's own; NOT the archive DB)
  "ambedkar-archive"      │          ├─ clickhouse  (traces, observations)
  api / worker ──http://langfuse:3000├─ redis       (queue, cache)
  (network ambedkar-archive_backend, └─ minio       (S3 event/media store)
   langfuse-web joins it with alias "langfuse")
```

- Separate compose file and project: `docker-compose.langfuse.yml`, project name `ambedkar-langfuse`. The core `docker-compose.yml` is unchanged.
- Separate data: its own Postgres, ClickHouse, Redis and MinIO, with its own named volumes (`ambedkar-langfuse_postgres`, `_clickhouse`, `_clickhouse_logs`, `_redis`, `_minio`). Nothing is shared with the archive database.
- Only `langfuse-web` publishes a port, on `127.0.0.1:3100` (host port 3000 was already taken). No other Langfuse service publishes anything; the data stores sit on an `internal: true` network with no egress.
- **How the archive reaches Langfuse:** through a shared Docker network. `langfuse-web` also joins the core project's existing `ambedkar-archive_backend` network with the alias `langfuse`. The archive therefore uses `ARCHIVE_LANGFUSE_HOST=http://langfuse:3000`. `host.docker.internal` was not used: it is Docker Desktop-only, and a Linux edge server would need `extra_hosts` added to the core compose file.
- Trade-off: on the shared network, `langfuse-web` can also reach the archive `db` container. This is acceptable for the local demo. For production, see "Production note".
- Service count: six (web, worker, Postgres, ClickHouse, Redis, MinIO). This is the minimum that Langfuse supports.

## Version compatibility (checked 2026-09-27)

| Item | Value | Source |
| --- | --- | --- |
| Backend SDK | `langfuse` 4.15.6 (Python SDK v4, OpenTelemetry-based), pinned in `backend/uv.lock`; also installed in the api image | `uv.lock`, `importlib.metadata` in host venv and api image |
| Server | `langfuse/langfuse` and `langfuse/langfuse-worker` **4.46.0** | Docker Hub tags; `/api/public/health` returns `4.46.0` |
| SDK ↔ server | Python SDK v4 needs server ≥ 3.63.0; server v4 fully supports it | langfuse.com/self-hosting/upgrade/versioning |
| v4 infrastructure | Same components as v3 (web, worker, Postgres, ClickHouse, Redis, S3). ClickHouse ≥ 25.12 (26.4 recommended); Redis ≥ 7.0 (7.2 recommended) | langfuse.com upgrade guide v3→v4 |
| Images used | `clickhouse/clickhouse-server:26.4`, `redis:7.4-alpine`, `postgres:17-alpine`, `cgr.dev/chainguard/minio:latest` (digest `sha256:bd014394a80898e68c149f2311fdf8d5a2c2f3bb2c33b9327ae6d02b4b065ae1`) | `docker image inspect` |

**No lighter supported option exists.** Langfuse v2 ran on Postgres alone, but it cannot accept SDK v3 or v4 traffic, because OpenTelemetry ingestion needs v3 or later. Langfuse also decided against a Postgres-only adapter for v3 and v4. Server v4 removed the legacy read endpoints (`GET /api/public/traces`, `/observations`, `/metrics`), so reads use the **Observations API v2** and Metrics API v2.

## Files

| File | Purpose | In git |
| --- | --- | --- |
| `docker-compose.langfuse.yml` | Langfuse stack: pinned images, healthchecks, memory caps, log rotation, `no-new-privileges` | yes |
| `.env.langfuse.example` | Variable names only | yes (`!.env.langfuse.example` in `.gitignore`) |
| `.env.langfuse` | Generated secrets and headless-init values | **no** (`.gitignore`: `.env.*` and an explicit `.env.langfuse`) |
| `deploy/langfuse/make_env.py` | Generates `.env.langfuse` and appends `ARCHIVE_LANGFUSE_*` to the root `.env`. Never prints values and never overwrites | yes |
| `deploy/langfuse/verify_trace.py` | Sends one real Ask and checks the trace in Langfuse. Prints only non-secret evidence | yes |
| `backend/archive/tracing.py` | Redaction hardening (below) | yes |
| `backend/tests/test_unit_tracing.py` | 18 redaction and export tests | yes |

## Secrets

- `python deploy/langfuse/make_env.py` writes `.env.langfuse` with fresh random values from Python's `secrets` module:
  - `NEXTAUTH_SECRET`, `SALT` and `ENCRYPTION_KEY` (256-bit hex each)
  - Postgres, ClickHouse, Redis and MinIO passwords
  - the initial user's password
  - a project key pair `pk-lf-<uuid4>` / `sk-lf-<uuid4>`
- It then appends three lines to the root `.env`: `ARCHIVE_LANGFUSE_PUBLIC_KEY`, `ARCHIVE_LANGFUSE_SECRET_KEY` and `ARCHIVE_LANGFUSE_HOST=http://langfuse:3000`. It first adds a newline, because `.env` had no trailing one. It skips this step if any `ARCHIVE_LANGFUSE_*` key already exists. No existing line was changed, and no value was printed.
- **Headless initialisation** (`LANGFUSE_INIT_*`) created organisation `ambedkar-archive`, project `archive-demo` ("Archive demo (redacted traces)"), the key pair above, and user `langfuse-admin@archive.local`. That user's password is only in `.env.langfuse`.
- `AUTH_DISABLE_SIGNUP=true`, so nobody else can register. `TELEMETRY_ENABLED=false`, so Langfuse sends no usage telemetry to langfuse.com.
- Rotation: stop the stack, delete `.env.langfuse`, rerun the generator, remove the old `ARCHIVE_LANGFUSE_*` lines from `.env` by hand, and start again. Headless init only creates resources that are missing, so rotate old API keys in the UI as well.

## Startup commands

Run from the repository root. The core stack must be up first, because the `ambedkar-archive_backend` network must exist.

```powershell
python deploy/langfuse/make_env.py                              # once; skips if .env.langfuse exists
docker compose -f docker-compose.langfuse.yml pull
docker compose -f docker-compose.langfuse.yml up -d
docker compose -f docker-compose.langfuse.yml ps                # web shows (healthy) after about 1-3 minutes
curl.exe http://127.0.0.1:3100/api/public/health                # {"status":"OK","version":"4.46.0"}
```

- UI: <http://localhost:3100>. Sign in as `langfuse-admin@archive.local`; the password is in `.env.langfuse`.
- Stop: `docker compose -f docker-compose.langfuse.yml stop`. Use `down` only with this `-f` file. **Never** use `-v`, and never run `down` on the core project.
- Upgrade: bump both Langfuse image tags together, then `pull` and `up -d`. Read the Langfuse upgrade notes first, and back up Postgres and ClickHouse before a major version.

## Resource use (measured 2026-09-27, Docker Desktop, 7.6 GiB VM, 20 CPUs)

Memory and CPU were read with `docker stats --no-stream`, at idle, after the verification traces:

| Service | RAM used / cap | CPU |
| --- | --- | --- |
| langfuse-web | 875 MiB / 1280 MiB | ~2% |
| langfuse-worker | 472 MiB / 768 MiB | 4–22% |
| clickhouse | 834 MiB / 1280 MiB | 15–60% (background merges) |
| minio | 145 MiB / 256 MiB | <1–30% |
| postgres | 59 MiB / 256 MiB | ~0% |
| redis | 24 MiB / 128 MiB | ~2% |
| **Total** | **≈ 2.4 GiB** (caps sum to 3.9 GiB) | |

Disk:

- Volumes, from `docker system df -v`: ClickHouse 115.5 MB, Postgres 71.7 MB, ClickHouse logs 13.0 MB, MinIO 50 kB, Redis 27 kB, for **≈ 200 MB** in total with two traces. That is mostly schema and migrations; trace data grows from here.
- Images: web 1.79 GB, worker 1.84 GB, ClickHouse 1.14 GB, Postgres 424 MB, MinIO 243 MB, Redis 58 MB, for **≈ 5.5 GB** in total.

Notes:

- Node heap caps: web started with `--max-old-space-size=512` and failed with "JavaScript heap out of memory". It is now 768 MB, with a 1280 MiB container cap. The worker runs with 512 MB inside a 768 MiB cap.
- On this demo machine the core stack plus a live ingest already used about 4–5 GiB. After Langfuse started, the VM had about 2 GB available and swap was full. This is the §3.4 signal: on a 32 GB edge server the fit is comfortable, but on smaller hardware Langfuse should move to a separate machine (below).

## Redaction rules (what leaves the archive)

Traces are built in `backend/archive/tracing.py`. Every value passes through `redact()` before it reaches the SDK. The SDK's `mask=` hook applies `redact()` again at export.

**Sent:**

- Trace name (`ask`, `ingest.run`, `ingest.publish`).
- `session`: the first 16 hex characters of the SHA-256 of the browser's random session id. The raw id is never sent.
- `question`: the visitor question after PII scrubbing, which spec §6.6 allows. Setting `ARCHIVE_TRACE_QUESTION_MODE=hash` sends only `sha256:…`.
- `index_version`, `prompt_version` (also sent as the Langfuse observation `version`), and node names.
- Passage **ids**, rerank scores, candidate counts and the reranker name.
- Model, input and output tokens, cached tokens, cost when priced locally (otherwise Langfuse infers it from its price table), latency and provider latency.
- Validation `ok` and error codes, and the outcome.
- Failures: level `ERROR`, with a status message after scrubbing.

**Never sent:**

- Passage text or excerpts, generated answer sentences, prompts, or conversation history.
- The raw session id, IP addresses, user agents, or authorization headers.
- API keys and other secrets.

**Changes made on 2026-09-27 (surgical; tests in `backend/tests/test_unit_tracing.py`):**

1. `scrub_pii` now also removes IPv4 and IPv6 addresses (`[ip]`) and secret-shaped tokens (`[secret]`): `sk-`/`pk-`/`rk-` keys including `sk-lf-` and `sk-proj-`, `Bearer …`, JWTs, AWS `AKIA…`, and `password=`/`token=`/`api_key=` pairs. The existing email, phone, Aadhaar and PAN rules are unchanged. Clock times such as `11:35:20`, verse-style references such as `3:16`, and `sha256:` question hashes are left alone. Because `question_ref` uses the same scrubber, the `answer_log.question_ref` stored in the database is now scrubbed the same way.
2. `redact()` drops these keys, case-insensitively:
   - Archive text: `excerpt`, `sentences`, `answer`, `raw_answer`, `quoted_spans`, `quotes`, `prompt`, `system_prompt`, `messages`, `history`.
   - Identifiers and secrets: `session_id`, `ip`, `client_ip`, `remote_addr`, `x_forwarded_for`, `user_agent`, `email`, `authorization`, `cookie`, `api_key`, `password`, `secret`, `token`, `jwt`.
   - The original `text`/`content`/`context` rules remain.
3. The Langfuse client is created with `should_export_span=is_langfuse_span`. The SDK's default would also export third-party `gen_ai.*` OpenTelemetry spans, and those bypass `mask`. None are installed today; the filter keeps it that way.
4. Failures: exceptions and span-level `error` values set `level=ERROR` and a scrubbed `status_message`. Spec §4.9 requires failures in the trace.
5. Prompt version: set as the Langfuse `version` on the root span and on the generation, so traces can be filtered and compared by prompt version.
6. Cost: `cost_details` is sent only when the archive computed a non-zero cost. With `ARCHIVE_LLM_*_COST_PER_MTOK` unset, Langfuse prices `gpt-4o-mini` itself.

A red/green check confirmed the tests. Against the original `tracing.py`, 12 of the then-15 tests failed; with the change, all 18 pass (`pytest tests/test_unit_tracing.py tests/test_unit_gate_and_validation.py`: 45 passed).

Residual: the root span metadata also carries OpenTelemetry resource attributes added by the SDK (`service.name`, SDK version, and the project **public** key, which is not a secret).

## Verification evidence (2026-09-27)

The running api and worker were not rebuilt or recreated, because another engineer was ingesting through them. Verification used a one-off container from the existing api image. It had the working-tree `tracing.py` and `verify_trace.py` mounted read-only. Its memory was capped at 1.2 GB, and it used the lexical reranker, because the VM had only about 2 GB free. That setting affects which passages rank, not the tracing path.

```powershell
docker compose run -d --rm --no-deps --name lf-verify -e ARCHIVE_RERANKER_BACKEND=lexical `
  -v "C:/Users/cvbal/Desktop/lessgooo/backend/archive/tracing.py:/app/archive/tracing.py:ro" `
  -v "C:/Users/cvbal/Desktop/lessgooo/deploy/langfuse/verify_trace.py:/verify/verify_trace.py:ro" `
  api sleep 900
docker update --memory 1200m --memory-swap 1200m lf-verify
docker exec lf-verify python /verify/verify_trace.py
docker stop lf-verify
```

- Reachability from the one-off container: `http://langfuse:3000/api/public/health` returned `{"status":"OK","version":"4.46.0"}`, and `tracing.backend_name()` returned `langfuse`. The mounted `tracing.py` SHA-256 matched the working tree.
- Keys: `GET /api/public/projects` returned 200 and project `archive-demo`; wrong keys returned 401.
- Live LLM calls: **2** gpt-4o-mini calls in total (limit 5).

**Run 1, about 12:24 IST, answer 18.** The Ask abstained (`insufficient`, no LLM call) because the lexical reranker scored below the 0.35 threshold. The trace arrived, but the check found a real leak. An IPv4 address followed by a sentence-ending period (`from 192.168.1.50.`) was not scrubbed. The pattern's lookahead rejected the trailing dot, and the unit test had only tried an IP followed by a space.

- Fixed in `_IPV4`, with trailing-punctuation test cases added.
- That trace (`e4ba8b4c…`) was deleted with `DELETE /api/public/traces/{id}` (200), and re-querying showed 0 observations.
- The IP was synthetic, from a private range. Answer-log row 18 in the archive database still holds that unscrubbed synthetic question. It was left alone because the database is outside this task.

**Run 2, 12:29 IST, answer 20.** The Ask was `answered` with the trace present, but two gaps showed. The verifier read the model from the wrong API field. Cost was 0, because the archive sent `cost_details.total = 0` and so overrode Langfuse's price table. That led to change 6 above.

**Run 3, 12:32 IST, answer 24: final.** Question: `Email p<random>@x.in, IP 10.0.0.7. According to the lecture on education, why should mothers learn to read?` Session id: `lf-verify-session-<uuid4>`. Result, read back from `GET /api/public/v2/observations?traceId=…`:

| Check | Result |
| --- | --- |
| Trace id / outcome | `5d050577bbeec6e77ecca05a27262805`, `answered`, citation passage 7 (synthetic fixture `fx-lecture-education`), no cache hit |
| Observations | SPAN `ask` (root), `check_input`, `detect_language`, `rewrite`, `retrieve`, `validate`, `finalize`; GENERATION `generate` |
| Latency | Root `ask` 11.92 s (answer log `latency_ms` 13458 includes database work); provider latency 2346 ms in generation metadata |
| Token usage | input 1101, output 44, total 1145 (matches answer log 24) |
| Cost | $0.00019155 (input $0.00016515 + output $0.0000264), Langfuse price table, model `gpt-4o-mini-2024-07-18` |
| Prompt version | `version = ask-v1` on root and generation; `metadata.prompt_version = ask-v1` |
| Question as stored | `Email [email], IP [ip]. According to the lecture on education, why should mothers learn to read?` (the answer log's `question_ref` has the same placeholders) |
| Leak checks over the full returned JSON | visitor email: absent; email local-part: absent; IP: absent; raw session id: absent; passage excerpt text: absent; generated answer text: absent; LLM API key: absent; Langfuse secret key: absent; JWT secret: absent |
| Environment | `demo` |

Afterwards, the project held exactly two traces (runs 2 and 3), both `ask`.

Side effects in the archive database: answer-log rows 18, 20 and 24, plus answer-cache entries for the two answered, uniquely worded questions. These are the same rows a visitor Ask creates.

Known limitation: the `generate` observation is recorded after the graph finishes, so its own Langfuse latency is 0. Real provider latency is in its metadata (`latency_ms`), and the root span's latency is the end-to-end figure. Fixing this means timing the generation inside `ask/graph.py`, which is outside this task.

## Apply to the running stack (NOT done; do when ingestion allows)

The running `api` and `worker` read `.env` only when their containers are created. Right now they still trace to the local JSONL sink, and their image contains the **old** `tracing.py`. Once the other engineer's ingest is finished:

```powershell
# 1. Langfuse must be up and healthy
docker compose -f docker-compose.langfuse.yml ps
# 2. Rebuild the api image so it contains the new backend/archive/tracing.py
#    (the worker uses the same image, ambedkar-archive/api:local)
docker compose build api
# 3. Recreate only api and worker; db and proxy are left alone, and no volume is touched
docker compose up -d --no-deps --force-recreate api worker
# 4. Check
docker compose exec api python -c "from archive import tracing; print(tracing.backend_name())"   # langfuse
curl.exe -k https://localhost:8443/api/health/ready     # includes "trace_backend": "langfuse"
```

- If you only need the new keys and not the new redaction, skip step 2. **Not recommended:** the old image lacks the IPv4 and secret scrubbing and the third-party span filter.
- Do not run `docker compose down` on the core project.
- The ingest `worker` also emits `ingest.run` / `ingest.publish` traces (item ids, page counts and results only).

## Moving Langfuse to a separate machine (§3.4)

1. Copy `docker-compose.langfuse.yml`, `deploy/langfuse/make_env.py` and `.env.langfuse` to that machine.
2. There is no archive network on that machine, so run `docker network create langfuse_edge` and start with `LANGFUSE_ARCHIVE_NETWORK=langfuse_edge`.
3. Publish the UI and API behind TLS: either a reverse proxy on that host, or change the port binding from `127.0.0.1` to the LAN interface and firewall it to the edge server's address only.
4. On the edge server, set `ARCHIVE_LANGFUSE_HOST=https://<langfuse-host>` in `.env`, then recreate `api` and `worker`.

## Production note

For [PROD] (spec §9, "Monitoring + Langfuse"):

- Run Langfuse on its own host or VM, not on the app servers, behind TLS, on the staff and monitoring network only.
- Keep secrets in the institution's secret manager instead of `.env.langfuse`.
- Pin the MinIO image by digest, or use institutional S3-compatible storage.
- Back up the Langfuse Postgres and ClickHouse separately from archive backups. Langfuse data is operational telemetry, not the audit record, so losing it must never affect archive integrity.
- Keep `AUTH_DISABLE_SIGNUP=true` and SSO for staff.
- Do not attach it to the archive database network; reach it by URL.
- `deploy/production/` was not changed.

## Skills used

| Skill | Source | Effect on this work |
| --- | --- | --- |
| find-skills | `C:\Users\cvbal\.agents\skills\find-skills\SKILL.md` | Search order: local skills first, then skills.sh and vendor docs. That led to the official Langfuse skill below. |
| docker-development | `~/.claude/plugins/cache/claude-code-skills/engineering-advanced-skills/2.2.0/docker-development` | Compose checklist: pinned tags, a healthcheck on every data store and the web service, memory caps, named volumes, explicit networks with `internal: true` for back-end services, only the needed port exposed, env files for secrets, log size limits. |
| env-secrets-manager | same plugin, `env-secrets-manager` | Secrets are generated locally into a gitignored file; the tracked example has names only; nothing is printed; rotation steps are written down. |
| observability-designer | same plugin, `observability-designer` | Span design (one root per Ask, a node span per graph step, a typed generation), failures as `ERROR`, cost and latency as first-class fields, data privacy in telemetry. |
| verification-before-completion | `~/.claude/plugins/cache/claude-plugins-official/superpowers/6.4.1/skills/verification-before-completion` | No claim without fresh evidence. A red/green run proved the unit tests catch the redaction gaps. The live read-back then found two defects the tests had missed, the IPv4 leak and the zero-cost override; both were fixed and re-verified before LP-12 was marked verified. |
| senior-devops | same plugin as docker-development | Considered; it covered nothing beyond docker-development for a single-host compose stack, so it was not applied separately. |
| langfuse (official) | [github.com/langfuse/skills](https://github.com/langfuse/skills), `skills/langfuse/SKILL.md` and `references/instrumentation.md`; read, not installed | Fetch current docs rather than rely on memory. Check the baseline: model, tokens, names, hierarchy, observation types, masking. Run the path and fetch the trace back to audit it (the step that found both defects). Use v4 APIs. |
| Langfuse official docs | langfuse.com (self-hosting Docker Compose, headless initialisation, versioning matrix, v3→v4 upgrade guide, Observations API v2) | Image versions, required components and minimum versions, `LANGFUSE_INIT_*`, v2 read APIs, and confirmation that there is no lighter topology. |
