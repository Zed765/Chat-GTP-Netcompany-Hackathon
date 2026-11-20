"""Tests never call a real model: whatever the shell exports, they see a key that opens
nothing and an address where nothing listens. Model calls are answered by test doubles."""

import os

os.environ["OPENAI_API_KEY"] = "not-a-real-key"
os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:9/v1"
