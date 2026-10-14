# Verification ledger

Do not infer completion from a build or a screenshot.

| Gate | Result |
|---|---|
| Separate local project | Created; synced sources untouched |
| Dedicated API key | Stored privately on Render with explicit approval October 14; real hosted Responses API proposal succeeded |
| Node can launch Git | EPERM in sandbox; successful with approved external execution |
| New private source repository | raineslc/home-headquarters; privacy verified |
| Render workspace | Home Headquarters; selected by user; initially empty |
| Hosting costs | User chose free testing; paid resources are not approved |
| Versioned schema | Initial Django migration generated |
| Django deployment security check | Passed locally |
| Export input validation | Passed locally |
| PostgreSQL integration tests | Passed on PostgreSQL 17 in GitHub Actions run 38313660452, commit 3bf9a3f0c5043ae04a7e0123ede0a7306126a076 |
| Deployed build | Passed: free Render web srv-db6ps0on74is738hm5qg, deployment dep-db6ps10n74is738hm6jg; unauthenticated home redirects to sign-in |
| Real owner sign-in | Verified in deployed browser as Chris Raines, household Raines |
| Persist and retrieve record | Verified: created a deployment note and retrieved it after reload |
| Isolated deployed recovery | Pending |
| Browser accessibility/responsive QA | Desktop dashboard and lunch layout checked. Phone viewport override had no effect; mobile visual QA remains pending |
| Unattended scheduler execution | Pending paid scheduling approval |
| Reminder delivery while app closed | Not implemented; unverified |
| Calendar synchronization | Chris connected; selected calendars manually synced and Google event verified in unified calendar. Scheduled sync and writes remain pending |

The current artifact is a preview, not the full family organizer release. Family profiles, one-off activities, linked tasks, monthly lunch plans, invitations, read-only Google connections and approval-based AI are implemented. A hosted full-household recovery drill, Google writes, unattended sync and reminder delivery remain outstanding.

Test URL: https://home-headquarters-test.onrender.com

Free PostgreSQL 17 instance: dpg-db6prh0n74is738hk9s0-a. It expires November 11, 2026 at 9:56 PM America/New_York (November 12 at 02:56 UTC). Do not treat the free database as long-term storage.

OWNER_EMAIL was omitted during the initial Blueprint setup. It was added through the Render connector, preserving existing secrets, and deployment dep-db6q17aj9qps73a2m27g was triggered. First-user setup remains pending. No paid scheduler was created.

## Organizer preview verification

- First-user setup subsequently completed by Chris. Browser sign-in and record persistence verified.
- PostgreSQL CI run 38399801696 passed for commit c69a33728e9208a71eb8fe1f618b0102944a9762.
- Render deployment dep-db72go942hec73f56kng is live with migration 0002.
- Chris, Melissa, Logan and Henry were created through the live family form using the user-provided names and roles; these are editable database records, not schema fixtures.
- Live lunch test applied Pack lunch to October 13 and 14 for Henry, verified Today, then used Undo. Both dates returned to Not decided.
- No sample activities/tasks were added to the real household. Their workflows were verified with isolated PostgreSQL test data in CI.

## AI assistant, October 14, 2026

- Migration 0005 adds proposal history, suggestions, usage limits, saved reminder preferences and task search prompts.
- PostgreSQL CI run 38567894258 passed, including eight assistant workflow/security tests, commit da819bdcbeac24ffeea7699209cb3dda564c216e.
- Render deployment dep-db7np4ui0phs739b9t10 succeeded; approved key configuration deployed as dep-db7npoqj9qps73d40kv0.
- A real hosted birthday-party request returned an editable draft and resolved Saturday to October 17. No calendar event or task was approved or created during this live check.
- That probe exposed an ambiguous gift-recipient assumption. Instructions were refined and a second real synthetic request returned a neutral Birthday party title, the three preparation tasks, and questions about recipient identity, age and budget.
- Assistant changes are backed up in the ignored local Git bundle and private GitHub repository. Keys are excluded from both.
- Reminder delivery remains disabled; the UI saves preferences without claiming notifications were scheduled.

## Full household recovery (REC-01), October 14, 2026 — Claude Code

- Branch rec-01-full-household-recovery adds export format version 2, validated replacing restore, migration 0006 (PendingRestore) and the export_household command.
- Local isolated PostgreSQL 16 (portable pgserver build; CI uses 17) with Python 3.11: 43 organizer tests passed, including a round-trip recovery drill into a separate household, same-household restore and undo via recovery point, 20 invalid-export cases, per-parent/expiring previews, stale-preview rejection, version 1 compatibility and secret exclusion. Deploy check, migration drift check and collectstatic passed.
- GitHub Actions CI run 38578064839 (PostgreSQL 17, Python 3.13.7) passed for commit 4c1323b3e4909f872bf780247abc75153811aa7a.
- Not yet verified: deployment, a real export downloaded from the live preview, and restore of that export into an isolated hosted environment. The real household database was not touched.

## Upcoming agenda (DASH-03), October 14, 2026 — Claude Code

- New isolated PostgreSQL test covers the rolling range, task inclusion/exclusion (completed, out of range, other household), ordering and Overdue list. 44 organizer tests passed locally.
- Visual check at phone width against a local test database with sample data (not the real household). Desktop layout reuses the existing agenda styles.

## Repeating activities and tasks (CAL-02, TSK-02), October 14, 2026 — Claude Code

- Migration 0007 and python-dateutil 2.9.0.post0. 22 new isolated PostgreSQL/unit tests: rule building, description and validation; Option A spring-forward/fall-back times; multi-day overlap; week/month/agenda expansion; only-this, this-and-following and all edits (including pattern changes and date shifts); deletes; stale-edit conflict; repeating task creation once, end by count, skip/stop; export version 3 round trip into a separate household; version 2 compatibility; invalid recurrence exports. 66 organizer tests passed locally.
- Visual check at phone width on a local test database: repeat controls show only the relevant fields; occurrence detail, scope choice and repeating-task badge render correctly. Real household data was not used.

## Overview task priority filters (DASH-04), October 14, 2026 — Claude Code

- Isolated PostgreSQL test covers ordering, each filter's membership and count (overdue included in due filters; completed and other-household tasks excluded), an unknown filter falling back to All, and the filtered empty state. 67 organizer tests passed locally.
- Visual check on a local test database (sample data only): filter row with counts and the Due in 1 day filter.

## Multi-date activity entry (CAL-03), October 14, 2026 — Claude Code

- Five isolated PostgreSQL tests: default range and 120-day cap; review then create with sorted, de-duplicated dates, participants, conflicts listed and one household version bump; repeated batch adds nothing; a clock-change problem on one date blocks all dates; invalid, out-of-range and over-limit dates, missing title, end before start and another household's member rejected; all-day dates; changing the range keeps details and in-range dates. 72 organizer tests passed locally.
- End-to-end at phone width on a local test database: weekday toggle selected six Saturdays, review listed them, and creation added six activities sharing one batch. Real household data was not used.
