from app import app  # Import the Flask app object from app.py
import platform
if platform.system() == "Windows":
    import win32api  # or other pywin32 modules

if __name__ == "__main__":
    app.run(debug=True)