import re
import secrets
from werkzeug.security import generate_password_hash, check_password_hash

def validate_password(password: str) -> tuple[bool, str]:
    """
    Requirement from Brightloop PDF:
    "the password must be more than eight characters, with an uppercase letter,
    a lowercase letter and a special character."
    """
    if not password or len(password) <= 8:
        return False, "Password must be more than 8 characters long."
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r'[^A-Za-z0-9]', password):
        return False, "Password must contain at least one special character."
    return True, ""

def hash_password(password: str) -> str:
    return generate_password_hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return check_password_hash(hashed, password)

def generate_reset_token() -> str:
    return secrets.token_urlsafe(32)
