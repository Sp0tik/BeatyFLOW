# Production hardening — 2026-10-01

Implemented:

- removed shipped `.env`; sanitized `.env.example`; added `.gitignore` / `.dockerignore`;
- server-side slot revalidation before create/reschedule;
- PostgreSQL advisory transaction lock + exclusion constraint against overlapping active bookings;
- active-master validation + one-time stronger auth codes + failed-attempt throttling;
- PostgreSQL backup/restore scripts and Compose backup profile;
- Redis FSM storage;
- resilient reminder catch-up logic;
- client rescheduling;
- split working intervals / breaks;
- vacation date ranges;
- completed / no-show workflow;
- owner analytics;
- client cards;
- marketing opt-in / opt-out;
- broadcast delivery success/failure statistics;
- price snapshot on booking for historical revenue analytics;
- unit/security smoke tests.

Manual action still required: revoke the old Telegram bot token in BotFather and put a newly generated token only in the private `.env` on the deployment host.
