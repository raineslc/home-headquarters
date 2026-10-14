# Home Headquarters

Shared product brief for ChatGPT/Codex, Claude Code, and human contributors.
Read AGENTS.md before making changes. TASKS.md is the authoritative prioritized checklist;
CHANGELOG.md records completed changes. Chat history is context, not the handoff artifact.

## Purpose

A private organizer for two parents and two children: Chris, Melissa, Logan, and Henry.
These are editable household records, never hard-coded application identities. Parents
have independent accounts and share plans within one household. The app should answer
what happens today/this week, who participates, what preparation is needed, and which
children need packed lunches. AI helps organize and prepare research; humans approve writes.

## Current product

Working preview, **not production-ready**. Includes authenticated household access,
editable family profiles, parent invitations, calendar week/month/Upcoming agenda, one-off
and repeating activities, linked and repeating tasks, high priority, monthly lunch planning, read-only Google
connections plus an opt-in family Google calendar the app writes to, and real OpenAI draft/review/approval
with explicit external task searches.
Chris's Google connection and hosted AI have been verified. Melissa's live sign-in and
calendar connection still need verification. See docs/verification.md for evidence.

Reminder preferences are stored, but notifications are not delivered. There is no
closed-app sync scheduler. Full household export/restore is implemented; its hosted recovery
drill, writable Google calendars and durable production storage remain release
requirements, not optional polish.

## Design and accepted changes

- White background, restrained green accents, subtle borders, readable type and spacing.
- Main weekly calendar, task priorities (all open tasks; filters All, High priority, Due in 7 days,
  Due in 1 day), compact inline Add activity/Add task, assistant input.
- "Add on several dates" adds one activity on many chosen dates after a review step.
- Agenda is a rolling seven-day Upcoming list of events and due tasks with an Overdue list.
- Google writes (owner decision, October 14, 2026): the app creates its own "Home Headquarters"
  calendar with the narrowest scope (calendar.app.created) and never changes other calendars.
  Each activity chooses whether it is added (on by default once set up). The app is the source
  of truth; edits made in Google are not copied back and are never overwritten silently.
- Repeating times on clock-change days follow Option A: skipped times move forward, repeated
  times use the first (owner decision, October 14, 2026; matches Google Calendar).
- No oversized greetings, slogans, decorative banners or setup details in everyday views.
- Keep Overview's removed “Next seven days” section and full lunch table removed.
- Show selected School lunch entries in the main calendar. Packed-lunch needs remain in
  the daily overview. Lunches uses a full month of school-day dates with bulk choices/undo.
- High-priority tasks appear first. Keep household and participant/source colors distinct.
- Phone and desktop support, keyboard access, labels, contrast, loading/empty/error states.
- Installable on Android (owner request): phones get a bottom tab bar; the week view lists days
  top to bottom; the app never stores family pages on the phone.

## Primary acceptance scenario

“Logan has a birthday party Saturday at 2 PM. We need a gift.”

Resolve Saturday against the household's current local date, not the displayed calendar
month. Ask about important missing details, including end time and whose birthday it is.
Do not infer Logan is the gift recipient. Propose buying a gift, wrapping it, and confirming
the address. Ask recipient age and budget for a useful editable search prompt. Allow
individual edits/approval/dismissal and approve-all. Approved tasks link to the activity
and appear in the organizer; retrying approval cannot duplicate records. Reminder delivery
is a pending acceptance gate. Model suggestions alone never authorize writes or purchases.

## Repository and operations

- Canonical source: https://github.com/raineslc/home-headquarters (private).
- Preview: https://home-headquarters-test.onrender.com
- Hosting workspace: Home Headquarters; web service home-headquarters-test.
- Only free hosting testing is approved. Paid hosting/scheduling requires owner approval.
- Free database expiry last recorded: November 11, 2026, 9:56 PM America/New_York.
  Verify in Render before relying on this date. Source backup is not a household-data backup.
- Preserve the older application, backups, existing Google grants and other hosted projects.
- No email ingestion, autonomous purchases, travel intelligence, chore rewards or document
  storage before first-release requirements are complete.

Use Git commits for every handoff. Start from the exact GitHub commit supplied by the
outgoing assistant, verify a clean checkout, and read all shared documents. Do not exchange
secrets or rely on copying a chat transcript to reconstruct source state.
