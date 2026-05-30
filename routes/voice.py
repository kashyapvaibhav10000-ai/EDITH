"""
routes/voice.py — All /voice/* endpoints.
Voice routes are registered via voice_routes.py (register_voice_routes).
This module re-exports that registration so chat_server can include it.
"""
# Voice routes are handled by the existing voice_routes.py module.
# chat_server.py calls register_voice_routes(app) directly.
# This file is a placeholder so the routes/ package is complete.
