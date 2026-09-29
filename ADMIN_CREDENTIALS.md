# Dr. B. R. Ambedkar Digital Heritage Archive — Staff & Admin Credentials

This document provides the authentication URLs and default credentials for staff workspaces, administrators, and reviewers.

---

## 1. Web Login Portals

| Workspace | URL | Description |
|---|---|---|
| **Staff & Admin Login (Dev Server)** | [http://localhost:5173/staff/login](http://localhost:5173/staff/login) | Direct Vite dev frontend |
| **Staff & Admin Login (Proxy / HTTPS)** | [https://localhost:8443/staff/login](https://localhost:8443/staff/login) | Production-like Caddy HTTPS proxy |
| **Staff & Admin Login (Proxy / HTTP)** | [http://localhost:8088/staff/login](http://localhost:8088/staff/login) | Plain HTTP proxy redirect |
| **Direct Workspace Dashboard** | [http://localhost:5173/staff](http://localhost:5173/staff) | Main archivist dashboard (once signed in) |

---

## 2. Default User Accounts & Credentials

### **A. System Administrator (Full Privileges)**
- **Email:** `admin@archive.local`
- **Password:** `admin-5okhuqepmt41g9`
- **Roles:** `["admin", "archivist", "curator", "reviewer"]`
- **Capabilities:** 
  - Manage all archival items, ingest batches, and metadata
  - Rights records and collection license registers
  - Review OCR, transcript segments, translations, and summaries
  - Curation: Timeline events, knowledge graph nodes & connections, stories, and Constitution article links
  - System audit logs and backup management

---

### **B. Demo Staff Accounts**

The following demo accounts are created during `bootstrap` with the common demo password:
- **Password (for all demo staff below):** `demo-archive-2026`

| Role | Email | Password | Assigned Roles | Permissions / Notes |
|---|---|---|---|---|
| **Lead Archivist** | `archivist@demo.local` | `demo-archive-2026` | `archivist`, `reviewer` | Ingestion, item review, metadata edits, withdrawals & restores |
| **Curator** | `curator@demo.local` | `demo-archive-2026` | `curator` | Timeline events, knowledge graph editing, curated stories, Constitution linkages |
| **Hindi Reviewer** | `reviewer-hi@demo.local` | `demo-archive-2026` | `translation_reviewer` (Hindi) | Review & approval of Hindi translations and OCR |
| **Marathi Reviewer** | `reviewer-mr@demo.local` | `demo-archive-2026` | `translation_reviewer` (Marathi) | Review & approval of Marathi translations and OCR |

---

## 3. Database & System Credentials

| Service | Environment Key / Parameter | Value |
|---|---|---|
| **PostgreSQL Database** | `POSTGRES_PASSWORD` | `archive-dev` |
| **PostgreSQL Connection** | `DATABASE_URL` | `postgresql+psycopg://archive:archive-dev@db:5432/archive` |
| **JWT Signing Secret** | `ARCHIVE_JWT_SECRET` | `g3ByhpjAFYdSb7XixO2NKtVZT8sJ0nWvQkUm9RMl` |
| **Langfuse Monitoring** | `ARCHIVE_LANGFUSE_PUBLIC_KEY` | `pk-lf-99847ae9-42df-429b-abae-7c6dd55c885b` |

---

## 4. API Authentication (For CLI / cURL / Postman)

To authenticate via API, send a `POST` request to `/api/staff/login`:

```bash
curl -X POST https://localhost:8443/api/staff/login \
  -k \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@archive.local",
    "password": "admin-5okhuqepmt41g9"
  }'
```

**Response:**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "email": "admin@archive.local",
    "name": "Administrator",
    "roles": ["admin", "archivist", "curator", "reviewer"],
    "languages": []
  }
}
```

Include the returned token in subsequent requests as:
```http
Authorization: Bearer <token>
```
