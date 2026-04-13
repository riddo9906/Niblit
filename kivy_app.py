"""
kivy_app.py — Niblit APK entry point.

This file is the Buildozer entry point when packaging the APK.
All UI and backend logic lives in niblit_dashboard.py (the canonical
Niblit Dashboard implementation).

Run locally::

    python kivy_app.py

Build APK::

    buildozer android debug

See niblit_dashboard.py for full documentation.
"""

from niblit_dashboard import NiblitKivyApp

if __name__ == "__main__":
    NiblitKivyApp().run()
