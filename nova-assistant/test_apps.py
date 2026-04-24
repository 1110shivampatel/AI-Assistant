import yaml
from safety.policy import SafetyPolicy
from tools.app_tools import AppLauncher

with open("config/settings.yaml") as f:
    config = yaml.safe_load(f)

policy = SafetyPolicy(config)
app = AppLauncher(config, policy)

tests = [
    "chrome.",
    "crove!",
    "CROVE!",
    "north.",
    "this calendar.",
    "Chrome",
    "notes",
    "challenges in the world.",
    "Open CROVE!",
]

for t in tests:
    result = app.resolve_app(t)
    name = result["name"] if result else "NOT FOUND"
    # Also check safety
    allowed, _ = policy.validate_app_launch(t, {"apps": app._apps})
    print(f"  {t:30s} -> {name:20s} (safety: {'PASS' if allowed else 'BLOCKED'})")
