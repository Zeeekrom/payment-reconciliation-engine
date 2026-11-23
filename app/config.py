"""Centralized configuration — Phase B, written by Claude.

Reuses a pattern proven useful in an earlier project: keep channel/model
related configuration in one place instead of scattering hardcoded values
across files.

Secrets may only come from environment variables (the .env file, already
listed in .gitignore, so it is never committed). This file itself must not
contain any real secrets.
"""

import os

from dotenv import load_dotenv

load_dotenv()  # Load the .env file from the project root (if present)

BIGMODEL_API_KEY = os.getenv("BIGMODEL_API_KEY")
BIGMODEL_BASE_URL = os.getenv("BIGMODEL_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")

# See docs/DESIGN_DECISIONS.md, D-001: two GLM model tiers, cheap/strong tiering
MODEL_CHEAP = os.getenv("MODEL_CHEAP", "glm-4-flash")
MODEL_STRONG = os.getenv("MODEL_STRONG", "glm-4-plus")
