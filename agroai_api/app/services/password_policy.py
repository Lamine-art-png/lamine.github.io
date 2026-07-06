from __future__ import annotations

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128


def password_policy_error(password: str, *, email: str | None = None) -> str | None:
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
    if email:
        local = email.split("@", 1)[0].casefold().strip()
        if len(local) >= 4 and local in password.casefold():
            return "Password must not contain your email name."
    if len(set(password)) == 1:
        return "Choose a less repetitive password."
    return None
