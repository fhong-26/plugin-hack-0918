def validate_identity(store, session_id, now):
    """Return an active session's user ID, or None when access is denied."""
    session = store.get_active_session(session_id, now)
    return None if session is None else session["user_id"]
