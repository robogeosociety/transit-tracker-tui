import os
import sys

from pydantic import ValidationError

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from transit_tracker.config import TransitConfig


def validate_config(path):
    print(f"Validating {path}...")
    if not os.path.exists(path):
        print(f"Error: File {path} not found.")
        return False

    try:
        config = TransitConfig.load(path)
        print("✅ Configuration is valid!")
        print(f"   API URL: {config.api_url}")
        print(f"   Stops: {len(config.transit_tracker.stops)}")
        print(f"   Subscriptions: {len(config.subscriptions)}")
        for sub in config.subscriptions:
            print(
                f"     - {sub.label} ({sub.route} at {sub.stop}) "
                f"[offset: {sub.time_offset}]"
            )
        return True
    except ValidationError as e:
        print("❌ Configuration is INVALID:")
        print(e)
        return False
    except Exception as e:
        print(f"❌ An error occurred during validation: {e}")
        return False


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else ".local/home.yaml"
    if validate_config(path):
        sys.exit(0)
    else:
        sys.exit(1)
