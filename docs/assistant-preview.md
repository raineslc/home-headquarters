# Approval-based assistant preview

The Assistant page and overview composer call OpenAI Responses using `gpt-5-mini`.
Set `OPENAI_API_KEY` in Secret Manager (hhq-openai-api-key), never in source or
client JavaScript. `OPENAI_MODEL` is optional. The server sends the entered conversation,
current draft edits, local date/time zone, and active family names/roles/IDs. Existing
calendar entries are checked locally and are not sent to OpenAI. Requests set store=false.
Both active parents can see household proposal history. Avoid sensitive details in prompts.
Voice input (Speak button) uses the browser's own speech recognition; in Chrome, Google's
speech service transcribes the audio. The app receives only the resulting text.

Each request returns a strictly validated event/task proposal, including questions for
missing details. It cannot execute organizer writes. Approval validates again using the
normal organizer forms and locks the household and proposal in a database transaction.
Approve all is atomic. Duplicate approval is a no-op, even if the created record was later
deleted. Concurrent stale edits are rejected. Draft revisions and dismissal history persist.
Task completion is independent from suggestion approval. Approved preparation tasks link
to the approved activity. Approve or dismiss the event before approving a task individually.

Search suggestions are editable. The user must explicitly open the search review and
submit its query to Google. Opening an external search is not completed AI research and
never completes a task. Family names and email addresses are scrubbed from generated
search queries; the user reviews the entire query before sending it.

Limits: 30 generation attempts per household/local day and six per user/15-minute window.
Failures count toward the limits; requests do not retry automatically. An interrupted
generation can be retried after two minutes. One proposal supports one event and up to
eight preparation tasks. The assistant can suggest repeating activities and tasks; each
pattern is checked like a saved series and anything unusable becomes a question. Google
writes are not implemented.

Regression cases: `python manage.py assistant_eval` sends seven fixed planning requests to
the real provider (uses API credit) and checks the drafts. It creates a temporary household
inside a transaction that is rolled back, so no plans are kept. Run it with a key in an
ignored .env.local against an isolated database; add `--case NAME` to run one case.

Reminder preferences can be edited and saved, but **no reminder is scheduled or delivered**.
This is clearly labeled in forms and approval feedback. A paid scheduler/delivery setup
and closed-app delivery verification remain separate work. Household exports include
assistant plans and suggestions (see Settings → Backup and restore). Free preview database
expiry still applies.

Verification: isolated PostgreSQL CI covers approval, retry deduplication, linked tasks,
atomic rejection of incomplete events, draft edits, dismissal, household authorization,
stale versions, clarification history, AI schema validation, privacy scrub, API failure,
and explicit external searches. A real synthetic OpenAI request was successful before
deployment. Hosted end-to-end AI verification is recorded separately after configuration.
