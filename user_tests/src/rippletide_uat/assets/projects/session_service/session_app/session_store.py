"""In-memory session domain service; timestamps are caller-supplied UTC epochs."""


class SessionStore:
    def __init__(self, sessions=None):
        self._sessions = {session["id"]: dict(session) for session in (sessions or [])}

    def get_active_session(self, session_id, now):
        session = self._sessions.get(session_id)
        if session is None or session.get("revoked", False):
            return None
        if now > session["expires_at"]:
            return None
        return dict(session)
