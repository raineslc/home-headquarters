# Organizer preview

Current status: October 14, 2026. This is a working preview, not a production release.
All records use the same PostgreSQL database and parent authorization.

Available: week/month/agenda; timed/all-day/multi-day one-off activities; participants;
task assignment, completion timestamps, priority and activity links; editable/archivable
family profiles; monthly bulk lunch choices and version-protected undo; parent invitations;
per-parent read-only Google calendar sharing/manual sync; real OpenAI proposal review,
clarification, edits, approval/dismissal and explicit external task searches.

Overview combines local and selected Google events with due tasks. Weekly priorities
include overdue work; high priority sorts first. School-lunch selections appear on the
calendar, packed lunches in the daily overview. The full lunch table and “Next seven days”
section were removed from Overview by owner request. Quick activity/task forms are inline.

Still pending: bulk activity dates, Google writes,
unattended sync, real reminder delivery and the hosted full-household recovery drill. Melissa's live
account/calendar verification and complete release QA also remain. Reminder preferences
are saved only, and opening Google search is not completed AI research.

Migrations 0001–0007 preserve the existing foundation while adding organizer/connection/AI
tables. Exports include all household organizer data (format version 2). Production paid scheduling has not
been approved. Real-household sample AI proposals remain unapproved; creation/approval
tests use isolated PostgreSQL fixtures.

The shared checklist is [TASKS.md](../TASKS.md), product brief [PROJECT.md](../PROJECT.md),
implementation map [ARCHITECTURE.md](../ARCHITECTURE.md), working rules
[AGENTS.md](../AGENTS.md), and change history [CHANGELOG.md](../CHANGELOG.md).
See [verification.md](verification.md) for observed results and remaining gaps.
