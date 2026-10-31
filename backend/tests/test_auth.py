import unittest
from app.services.auth_service import hash_password, verify_password, create_access_token, decode_access_token


class TestAuthService(unittest.TestCase):
    def test_password_hashing_and_verification(self):
        password = "SecurePassword123!"
        hashed = hash_password(password)
        self.assertNotEqual(password, hashed)
        self.assertTrue(verify_password(password, hashed))
        self.assertFalse(verify_password("WrongPassword", hashed))

    def test_jwt_token_creation_and_decoding(self):
        user_id = 42
        role = "admin"
        token = create_access_token(user_id=user_id, role=role)
        self.assertIsInstance(token, str)
        self.assertTrue(len(token) > 20)

        payload = decode_access_token(token)
        self.assertEqual(payload["sub"], str(user_id))
        self.assertEqual(payload["role"], role)
        self.assertIn("exp", payload)


if __name__ == "__main__":
    unittest.main()

