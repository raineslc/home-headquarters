# Google Calendar connection

Each parent uses a separate parent sign-in. Settings → Parent accounts creates a
single-use, email-bound invitation, valid for two days. Share the link privately;
the app does not send invitations. The bearer link authorizes creation of that
email's account; email delivery/verification is not implemented in this preview.

## Deployment configuration

Use a dedicated OAuth Web application client for this deployment. Do not alter
old application credentials. Enable Google Calendar API in its Google Cloud
project. Configure External consent for the parents' Google accounts; in Testing,
add both as test users. Testing refresh tokens for calendar scopes expire after
seven days. No Google billing upgrade is required by this implementation.

Exact authorized redirect URI:
`https://home-headquarters-test.onrender.com/connections/google/callback/`

Set the following only in Render's secret environment settings:

- `GOOGLE_CLIENT_ID`: the Web application's client ID.
- `GOOGLE_CLIENT_SECRET`: its secret, never source-controlled or pasted into chat.
- `GOOGLE_TOKEN_KEY`: a stable Fernet key generated with
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
  in a private terminal. Store separately from database backups. Changing it without
  re-encryption requires both parents to reconnect.
- `GOOGLE_REDIRECT_URI`: the exact URI above (the deployment's default).

Requested scopes: `openid`, `userinfo.email`, `calendar.calendarlist.readonly`,
`calendar.events.readonly` (Google's standard full scope URLs in google_service.py).
Every sign-in sends `include_granted_scopes=true`, so reconnecting keeps earlier grants.

Optional write scope: `https://www.googleapis.com/auth/calendar.app.created`, requested only
when a parent chooses "Create the family calendar". It lets the app create calendars and
manage events only on calendars it created; it cannot read or change any other calendar.
**Before using it, add this scope in Google Cloud Console → Google Auth Platform → Data
access** for the dedicated OAuth client. In Testing mode, both parents remain test users.

## Family Google calendar (writes)

One parent chooses "Create the family calendar in <their account>" on the Google calendars
page. Google asks for the extra permission; the app creates a "Home Headquarters" calendar in
that account. Share it with the other parent in Google Calendar (Settings and sharing →
Share with specific people) so it appears on both phones.

Each activity then has "Also add to the family Google calendar" (on by default). Saving,
editing, unticking or deleting an activity updates Google after the change is saved here; a
Google problem never blocks or undoes the local change. The activity page shows the Google
status with Retry. Repeating series are sent as Google repeating events (with skipped dates);
a changed occurrence is a separate event.

- Edits made in Google are not copied back. If an event was changed in Google, the app stops
  and asks: use this version in Google, or keep Google's version and stop updating it.
- If an event was deleted in Google, it can be added again or left deleted.
- Deleting an activity removes its Google copy; if Google cannot be reached it stays queued
  under "Update Google now" on the Google calendars page.
- "Stop updating Google" keeps the calendar and its events in Google.
- Restoring a backup never changes the family Google calendar; restored activities start
  unticked.
- If that parent removes the permission or disconnects, updates fail visibly until the
  calendar is set up again.

Tokens are encrypted at rest with Fernet; only the refresh token is persisted.
Access tokens remain in server memory. OAuth uses session-bound state, expiry,
one-time callback processing and PKCE. Tokens are excluded from app exports.
Avoid HTTP access logs containing callback query strings or invitation URLs.
No provider error payload is shown to users or deliberately logged.

## Sharing and sync

New calendars default to Not shared. Busy-only choices discard titles, location,
and Google links before storage. Google private events always become Busy.
Each parent can edit only their own connection. Active parents in the same
household can see shared events. Disconnect removes cached events and credentials;
Google events remain untouched. Users may additionally revoke this dedicated
app's grant at https://myaccount.google.com/permissions.

Manual Sync now reads a complete window (past 90 days, next 366 days), with
pagination and recurrence expansion by Google. A successful atomic snapshot per
calendar removes deleted/cancelled instances. Failed pages preserve the previous
snapshot; errors and last-sync timestamps are visible. Retries are idempotent.
Generation/version checks reject stale concurrent syncs and sharing changes.
If both parents select the same calendar/event ID, it appears once, using the more
private cached representation. Invited copies across different Google calendars
are intentionally distinct.

The free deployment has no scheduler. Sync only runs on explicit Sync now.
Do not claim background sync or closed-app reminders. No recurring charges added.

## Verification

CI runs PostgreSQL tests for OAuth state/PKCE/CSRF/replay, encrypted storage,
unshared defaults, ownership/cross-household isolation, recurrence-instance snapshot
replacement, duplicate prevention, deletion, failed sync preservation, concurrent
choices, DST/all-day conversion, private-event redaction, invitations and expiry.
Provider calls in tests are fixtures, not proof of a real Google connection.
Release verification still requires each parent's consent and a real selected
calendar appearing in Overview, followed by a real Google change and resync.

## Recovery limits

Migration 0004 adds connection/cache/invitation tables without changing existing
plans. Migration 0009 adds the family calendar, write status fields and pending deletions. Household exports omit Google connections, calendars and cached events.
Provider caches can be rebuilt by reconnecting and syncing; household exports
cover local organizer data only. Never include tokens or invitation hashes in a user-facing export.
