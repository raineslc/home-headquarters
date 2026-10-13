# Verification ledger

Do not infer completion from a build or a screenshot.

| Gate | Result |
|---|---|
| Separate local project | Created; synced sources untouched |
| Dedicated API key | Created securely and saved in ignored .env.local; not deployed or exercised |
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
| Browser accessibility/responsive QA | Pending |
| Unattended scheduler execution | Pending paid scheduling approval |
| Reminder delivery while app closed | Not implemented; unverified |
| Calendar synchronization | Not implemented; unverified |

The current artifact is a preview, not the full family organizer release. Planner migration 0002 adds family profiles, one-off activities, preparation tasks and lunch plans. Full planner recovery, invitations, recurrence, Google sync, AI and reminders remain outstanding.

Test URL: https://home-headquarters-test.onrender.com

Free PostgreSQL 17 instance: dpg-db6prh0n74is738hk9s0-a. It expires November 11, 2026 at 9:56 PM America/New_York (November 12 at 02:56 UTC). Do not treat the free database as long-term storage.

OWNER_EMAIL was omitted during the initial Blueprint setup. It was added through the Render connector, preserving existing secrets, and deployment dep-db6q17aj9qps73a2m27g was triggered. First-user setup remains pending. No paid scheduler was created.
