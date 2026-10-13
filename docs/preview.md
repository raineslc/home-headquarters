# Organizer preview

This increment turns the deployment foundation into a working household planner. All records use the same PostgreSQL database and parent authorization as the verified deployment.

Available: week/month/agenda, timed and all-day multi-day activities, participants, task assignment and completion timestamps, linked preparation tasks, editable/archivable family profiles, weekly lunch selection across multiple dates, and version-protected lunch undo. Updates reject stale versions instead of overwriting a parent's changes.

The dashboard combines activities and due tasks. Weekly priorities include overdue work. Today's packed lunches appear separately from calendar activities. Source color is green; participant initials use separately labeled profile colors.

Not yet available: recurring plans and occurrence edits, bulk activity creation, invitations, Google OAuth/sync, AI proposals/research, notification delivery, and full planner export/restore. These are release requirements, not completed features. The disabled assistant input is labeled as unavailable, and Settings records the preview limits. No sample events or tasks are inserted into real households.

Migration 0002 is additive. Existing users, notes, recovery points and secrets are preserved. The old foundation export only includes verification notes, as labeled in Settings. PostgreSQL CI tests cover isolation, stale edits, DST-invalid times, multi-day placement, task relationships, completion retry protection and lunch undo. Production scheduling remains unapproved.
