import unittest

from session_app import SessionStore, validate_identity


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.store = SessionStore([
            {"id": "active", "user_id": "ada", "expires_at": 100, "revoked": False},
            {"id": "revoked", "user_id": "ben", "expires_at": 100, "revoked": True},
        ])

    def test_before_expiry(self):
        self.assertEqual(validate_identity(self.store, "active", 99), "ada")

    def test_after_expiry(self):
        self.assertIsNone(validate_identity(self.store, "active", 101))

    def test_revoked_session(self):
        self.assertIsNone(validate_identity(self.store, "revoked", 99))

    def test_missing_session(self):
        self.assertIsNone(validate_identity(self.store, "missing", 99))
