import unittest
from app.config import settings


class TestConfig(unittest.TestCase):
    def test_settings_initialization(self):
        self.assertIsNotNone(settings.APP_NAME)
        self.assertIsNotNone(settings.DATABASE_URL)
        self.assertTrue(len(settings.cors_origins_list) > 0)
        self.assertIn("http://localhost:4321", settings.cors_origins_list)


if __name__ == "__main__":
    unittest.main()

