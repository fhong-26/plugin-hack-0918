# Session service

Small session-domain library. Run `python -m unittest discover -s tests`.

The public API is `session_app.validate_identity(store, session_id, now)` and
`session_app.SessionStore(sessions)`. Session records have `id`, `user_id`,
`expires_at`, and `revoked`. Timestamps are explicit integer UTC epoch seconds.

The connected documentation and issue tracker contain the current requirements.
