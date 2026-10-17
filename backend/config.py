"""Static configuration: endpoints, paths and the identity we send to the wiki."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "osrs.db"
OVERRIDES_PATH = Path(__file__).resolve().parent / "overrides.toml"

# The wiki asks every client to identify itself with a project name and contact.
USER_AGENT = "osrs-gp-activity-finder/0.1 (+https://github.com/Wartimegaming/osrs-gp-activity-finder)"

PRICES_API = "https://prices.runescape.wiki/api/v1/osrs"
WIKI_API = "https://oldschool.runescape.wiki/api.php"

BUCKET_PAGE_SIZE = 5000
HTTP_TIMEOUT = 60
HTTP_RETRIES = 3

# Hourly price snapshots older than this are pruned.
SNAPSHOT_RETENTION_DAYS = 30
# Pause between historical /1h requests during backfill, to stay polite.
BACKFILL_DELAY_SECONDS = 1.0

COINS_NAME = "Coins"
