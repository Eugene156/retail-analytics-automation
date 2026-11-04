"""Generate ignored, local-only G0 test secrets without printing them."""

from pathlib import Path
import secrets


root = Path(__file__).resolve().parents[1]
env_path = root / ".local" / "g0" / ".env"
if env_path.exists():
    print("G0 secret file already exists; preserved.")
else:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "G0_POSTGRES_PASSWORD": secrets.token_urlsafe(36),
        "G0_API_TOKEN": secrets.token_urlsafe(36),
        "G0_N8N_ENCRYPTION_KEY": secrets.token_urlsafe(36),
        "G0_RUNNER_TOKEN": secrets.token_urlsafe(36),
    }
    with env_path.open("x", encoding="utf-8") as stream:
        for name, value in values.items():
            stream.write(f"{name}={value}\n")
    print("Created ignored local G0 secret file; values not displayed.")
