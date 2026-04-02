"""
api/app.py — Minimal, guaranteed Flask entrypoint for Niblit serverless.

This file provides a simple Flask WSGI app that is guaranteed to boot in
the Vercel Lambda runtime without importing any heavy agentic/orchestration
dependencies.  Advanced route mount logic can be incrementally re-added once
a minimal Flask API is confirmed running on Vercel Lambda.

Minimal vercel serverless boot fix.
"""

from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/")
def home():
    return jsonify({"status": "ok", "message": "Niblit minimal API is alive!"}), 200
