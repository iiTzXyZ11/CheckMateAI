import secrets
import platform
if platform.system() == "Windows":
    import win32api  # or other pywin32 modules
secret_key = secrets.token_urlsafe(32)
print(secret_key)