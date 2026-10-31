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

    def test_admin_user_lifecycle_endpoints(self):
        """Verify admin password reset, account deletion, and self-deletion guard."""
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as client:
            # 1. Login as admin
            login_res = client.post("/api/v1/auth/login", json={
                "email": "admin@brightloop.io",
                "password": "BrightloopAdmin2026!"
            })
            self.assertEqual(login_res.status_code, 200)
            admin_data = login_res.json()
            admin_headers = {"Authorization": f"Bearer {admin_data['access_token']}"}

            # 2. Self-deletion must be forbidden
            del_self_res = client.delete(f"/api/v1/auth/users/{admin_data['user_id']}", headers=admin_headers)
            self.assertEqual(del_self_res.status_code, 400)

            # 3. Create a test user to manipulate
            import uuid
            test_email = f"temp_{uuid.uuid4().hex[:6]}@brightloop.io"
            reg_res = client.post("/api/v1/auth/register", json={
                "full_name": "Temporary Test User",
                "email": test_email,
                "password": "InitialPassword2026!"
            })
            self.assertEqual(reg_res.status_code, 201)
            temp_user_id = reg_res.json()["user_id"]

            # 4. Admin changes password for this user
            pwd_res = client.put(
                f"/api/v1/auth/users/{temp_user_id}/password",
                json={"password": "NewUpdatedPassword2026@"},
                headers=admin_headers
            )
            self.assertEqual(pwd_res.status_code, 200)

            # Verify the user can login with the new password
            login_new_res = client.post("/api/v1/auth/login", json={
                "email": test_email,
                "password": "NewUpdatedPassword2026@"
            })
            self.assertEqual(login_new_res.status_code, 200)

            # 5. Admin deletes the test account
            del_res = client.delete(f"/api/v1/auth/users/{temp_user_id}", headers=admin_headers)
            self.assertEqual(del_res.status_code, 200)

            # Verify account is deleted and cannot login
            login_deleted = client.post("/api/v1/auth/login", json={
                "email": test_email,
                "password": "NewUpdatedPassword2026@"
            })
            self.assertEqual(login_deleted.status_code, 401)


if __name__ == "__main__":
    unittest.main()

