"""Publish static assets and seed only the explicitly selected demo database."""
import os
import shutil
from pathlib import Path

if Path("static").exists():
    shutil.copytree("static", "public/static", dirs_exist_ok=True)
if os.environ.get("PORTFOLIO_DEMO") == "1":
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError("A dedicated DATABASE_URL is required for the demo build")
    from seed_demo import seed
    seed()
