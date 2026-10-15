# BEAUTYFLOW — Telegram Booking Bot for Beauty Salons

BEAUTYFLOW is a Telegram booking bot and lightweight CRM for beauty salons, built with **Python, aiogram 3, PostgreSQL, SQLAlchemy (async), Alembic, and Redis**. The current setup is designed for one salon per bot instance.

## Features

### Clients
- Book an appointment by selecting a master, service, date, and available time.
- View upcoming appointments and cancel or reschedule bookings.
- Choose whether to receive marketing messages (opt-in / opt-out).
- Continue receiving essential appointment reminders independently of marketing preferences.

### Masters
- One-time account linking with the `/master <code>` command.
- View appointments and manage cancellations.
- Configure working hours and days off.
- Schedule vacation periods.
- Mark past appointments as `completed` or `no-show`.

### Salon owners
- Manage masters and activate or deactivate their accounts.
- Configure services, prices, durations, and working hours.
- Manage days off and vacation periods.
- Send marketing broadcasts and review delivery statistics.
- Access analytics and client profiles.

## Booking Integrity and Concurrency Protection

The booking flow does not trust an old inline-button selection. Before a booking is inserted, `create_booking()` revalidates:

- Whether the master and service are active.
- Booking horizon and whether the requested time is in the past.
- Days off and vacation periods.
- Working-hour intervals.
- The slot-grid step.
- Conflicts with existing active bookings.

Two database-level safeguards protect against overlapping bookings for the same master:

1. A PostgreSQL transaction advisory lock per master.
2. The `ex_bookings_master_time_overlap` exclusion constraint, introduced in migration `0006`, which prevents overlapping active booking time ranges for the same master.

## Working Hours and Breaks

A day can contain multiple working intervals. For example:

```text
Mon-Fri 09:00-13:00;14:00-18:00, Sat 10:00-15:00, Sun off
```

Commas separate day rules; semicolons separate intervals within the same day. In this example, 13:00–14:00 is a break and is not offered as an appointment slot.

## Vacation Periods

The days-off menu includes a vacation-period option. Enter a date range in this format:

```text
10.10.2026..20.10.2026
```

Each date in the range is added as a day off. Active appointments in the affected period are cancelled, and clients are notified.

## Appointment Reminders

The scheduler checks every five minutes for unsent reminders that have entered the configured `REMINDER_HOURS_BEFORE` window and whose appointments have not started yet. This helps reminders survive a brief restart or service interruption.

APScheduler is configured with `coalesce`, `max_instances=1`, and `misfire_grace_time`.

## Redis-Backed FSM

Conversation state is stored in Redis via `REDIS_URL`. This helps preserve booking and rescheduling steps across ordinary bot-container restarts.

## Security Notes

- **Never commit your `.env` file or include it in ZIP archives.** The repository should contain only the `.env.example` template; `.gitignore` and `.dockerignore` are configured to exclude `.env`.
- If a Telegram bot token has ever been exposed in an archive or repository, revoke it through BotFather and use a newly generated token.
- Master access codes are generated with `secrets.token_urlsafe(16)` and are single-use after successful account linking.
- The bot checks whether a master account is active and applies a limit to failed `/master` attempts.

## Getting Started

### Prerequisites

- Docker Engine and Docker Compose
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- Your Telegram user ID for `OWNER_TG_ID`

### Configure Environment Variables

1. Clone the repository and enter its directory:

   ```bash
   git clone https://github.com/Sp0tik/BeatyFLOW.git
   cd BeatyFLOW
   ```

2. Create your local environment file:

   ```bash
   cp .env.example .env
   ```

   On Windows PowerShell, use `Copy-Item .env.example .env`.

3. Set a **new** `BOT_TOKEN`, your `OWNER_TG_ID`, and a strong database password. Ensure the
