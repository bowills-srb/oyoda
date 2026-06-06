# Oyvoda Security & Compliance Documentation
# SOC 2 Readiness — Last Updated: March 2026

---

## 1. Vendor Risk Management (SOC 2 CC9.2)

All sub-processors handling Oyvoda customer data are documented below.
Each vendor was assessed for: SOC 2 certification, data residency, DPA availability, and retention policies.

| Vendor | Role | Data Handled | SOC 2 | DPA | Data Region | Retention |
|--------|------|-------------|-------|-----|-------------|-----------|
| **Supabase** | Database hosting | All operator + guest data | Type II | Available | AWS us-east-1 | Per operator policy |
| **Railway** | Application hosting | None persisted (runtime only) | Type II | Available | AWS us-east-1 | None |
| **Cloudflare** | CDN / DDoS / DNS | Traffic metadata only | SOC 2 | Available | Global edge | 24-48hr logs |
| **Groq** | LLM inference | Guest message content | Enterprise DPA | Available | US | Zero retention on inference |
| **Anthropic** | LLM fallback | Guest message content (rare) | Enterprise DPA | Available | US | Zero retention |
| **Twilio** | SMS/RCS delivery | Guest phone numbers, message content | SOC 2 Type II | Available | US | 3 days |
| **Escapia/Vrbo** | PMS integration | Booking data read-only | SOC 2 | Standard MSA | US | N/A (source of truth) |
| **GitHub** | Source code | Code only (no data) | SOC 2 Type II | Available | US | Per repo settings |
| **Sentry** | Error tracking | Error metadata (PII scrubbed) | SOC 2 Type II | Available | US | 90 days |

### Assessment Notes

**Groq:** Zero data retention confirmed in enterprise agreement. Message content sent for inference is not logged, stored, or used for training. Oyvoda's PII scrubbing layer removes guest identifiers before LLM calls as an additional control.

**Twilio:** Guest phone numbers are transmitted for SMS delivery. Twilio retains message metadata for 3 days. Oyvoda's guest consent flow (SMS opt-in) satisfies TCPA requirements before any message is sent.

**Supabase:** Primary data store. Row-level security enforced at application layer (company_id scoping). Supabase manages encryption at rest (AES-256) and daily backups with 7-day retention.

---

## 2. Incident Response Plan (SOC 2 CC7.3, CC7.4)

### Severity Definitions

| Level | Description | Examples | Response Time |
|-------|-------------|----------|---------------|
| **P0 — Critical** | Data breach, unauthorized access, service down | DB breach, credential leak, 100% outage | 1 hour |
| **P1 — High** | Partial data exposure, major feature down | Guest PII exposed to wrong operator, SMS down | 4 hours |
| **P2 — Medium** | Degraded performance, non-critical feature down | Slow responses, knowledge base unavailable | 24 hours |
| **P3 — Low** | Minor issues, cosmetic bugs | UI glitch, non-urgent edge case | 72 hours |

### Response Procedures

#### P0 — Data Breach

1. **Detect** — Sentry alert, operator report, or anomaly in audit log
2. **Contain** — Immediately rotate compromised credentials in Railway; if DB breach, contact Supabase support to disable external access
3. **Assess** — Query `security_audit_log` for scope: which operators, which data types, time window
4. **Notify** — Affected operators notified within **72 hours** via email to their registered address
5. **Remediate** — Patch root cause, deploy fix, confirm resolution
6. **Post-mortem** — Written root cause analysis within 14 days, shared internally
7. **Regulator notification** — GDPR: notify supervisory authority within 72 hours if EU data involved

#### P0 — Unauthorized Access (Credential Compromise)

1. Immediately rotate: `JWT_SECRET`, `OYVODA_MASTER_KEY`, all `OPERATOR_*` vars in Railway
2. Invalidate all active sessions (changing JWT_SECRET logs out all users)
3. Review `security_audit_log` for `AUTH_LOGIN_SUCCESS` events from unknown IPs
4. Notify affected operators within 72 hours

#### P1 — Cross-Tenant Data Leak

1. Identify the query or endpoint where company_id scoping failed
2. Deploy hotfix with corrected WHERE clause
3. Audit all affected requests in Railway logs
4. Notify affected operators within 24 hours

### Contact List

| Role | Contact | Escalation |
|------|---------|------------|
| Incident Commander | Daniel McKenzie | dhuntermckenzie@gmail.com |
| Security Contact | info@oyvoda.com | — |
| Supabase Support | support@supabase.com | enterprise@supabase.com |
| Railway Support | support@railway.app | — |
| Cloudflare Support | support@cloudflare.com | — |

---

## 3. Change Management Policy (SOC 2 CC8)

### Environments

| Environment | Purpose | Deploy Trigger | Approval Required |
|-------------|---------|---------------|-------------------|
| **Local** | Development | Manual | None |
| **Staging** | Pre-production testing | Push to `staging` branch | None |
| **Production** | Live | Push to `main` branch | Self-review checklist |

### Pre-Deploy Checklist (Production)

Before merging to `main`, the developer confirms:

- [ ] CI pipeline passes (security scan, lint, tests, Docker build)
- [ ] No secrets committed to code (check with `git diff --staged`)
- [ ] Database migrations are backward-compatible (no breaking schema changes)
- [ ] Rollback plan documented if migration is irreversible
- [ ] Environment variables updated in Railway if new config added
- [ ] `OYVODA_MASTER_KEY` and `JWT_SECRET` confirmed set in Railway
- [ ] Sentry DSN confirmed active (errors will surface within minutes of deploy)

### Rollback Procedure

1. In Railway: **Deployments** tab → find previous successful deployment → **Redeploy**
2. If DB migration was destructive: restore from Supabase backup (Dashboard → Backups)
3. Notify affected operators if rollback causes visible disruption

### Emergency Hotfix Process

For P0/P1 incidents requiring immediate production deploy:
1. Create fix on a branch, PR against `main`
2. Self-review — focus on: does this fix the issue, does it introduce new issues
3. Merge and deploy
4. Post-mortem within 24 hours documenting why normal process was bypassed

---

## 4. Access Control Policy (SOC 2 CC6)

### Operator Dashboard Roles

| Role | Description | Permissions |
|------|-------------|-------------|
| **Owner** | Full access | All operations including team management, billing, API keys |
| **Manager** | Property management | View/edit properties, approve inquiries, view financials |
| **Staff** | Day-to-day operations | View sessions, send messages, view properties |
| **Auditor** | Read-only compliance | Audit log, analytics only — no guest PII |

### Credential Requirements

- Passwords: minimum 12 characters (enforced at operator onboarding)
- JWT tokens: 15-minute access tokens, 30-day refresh tokens
- Refresh token revocation: immediate on logout
- Login lockout: 5 failed attempts → 15-minute lockout
- API docs (`/docs`, `/redoc`): disabled in production

### Quarterly Access Review

Every 90 days, review:
- Active operator accounts — remove inactive accounts
- Railway team members — confirm only active contributors have access
- Supabase team members — confirm only active contributors have access
- API keys — rotate any keys older than 90 days

---

## 5. Data Retention & Deletion (SOC 2 A1, GDPR)

| Data Type | Retention | Deletion Method |
|-----------|-----------|-----------------|
| Guest conversation records | 90 days post-checkout | Automated job (TODO: implement) |
| Escalation records | 12 months | Manual via dashboard |
| Security audit log | 7 years | Never delete manually (compliance) |
| API request logs (Railway) | 30 days | Railway auto-rotation |
| Operator account data | Duration + 30 days post-cancellation | Manual + automated |
| Supabase backups | 7 days rolling | Supabase auto-rotation |

### GDPR / CCPA Request Handling

Guest data deletion requests:
1. Operator receives request from guest
2. Operator logs into dashboard → Properties → Guest Sessions → [session] → Delete Guest Data
3. System anonymizes: replaces guest_name, guest_phone, guest_email with `[DELETED]`
4. Operator confirms deletion to guest within 30 days

---

## 6. SOC 2 Readiness Tracker

| Control | Status | Target Date | Owner |
|---------|--------|-------------|-------|
| TLS everywhere | ✅ Complete | — | Infrastructure |
| AES-256 field encryption | ✅ Complete | — | Engineering |
| bcrypt password hashing | ✅ Complete | — | Engineering |
| Audit log → Supabase | ✅ Complete | — | Engineering |
| Rate limiting | ✅ Complete | — | Engineering |
| Brute force protection | ✅ Complete | — | Engineering |
| Sentry error tracking | ✅ Complete | — | Engineering |
| API docs hidden in prod | ✅ Complete | — | Engineering |
| CI/CD pipeline | ✅ Complete | — | Engineering |
| Vendor risk documentation | ✅ Complete | — | This document |
| Incident response plan | ✅ Complete | — | This document |
| Change management policy | ✅ Complete | — | This document |
| Guest PII field encryption in DB | 🔄 In Progress | Q2 2026 | Engineering |
| Data retention automation | 🔄 Planned | Q2 2026 | Engineering |
| MFA for operator login | 🔄 Planned | Q3 2026 | Engineering |
| Penetration test | 🔄 Planned | Q3 2026 | External |
| Staging environment | 🔄 Planned | Q2 2026 | Engineering |
| SOC 2 Type II audit | 🔄 Planned | Q4 2026 | External auditor |
