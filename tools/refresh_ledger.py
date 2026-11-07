"""Daily refresh for the verifiable trade ledger (CLO-141): rebuild docs/status/ledger-latest.csv, then compare every
fill with the Pionex public klines and write docs/status/ledger-check-latest.json. Scheduled 08:00 local, before the
08:15 board report. Read-only; no secrets."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pionex_lab.reporting import trade_ledger

if __name__ == "__main__":
    rc = trade_ledger.main(["build"])
    rc |= trade_ledger.main(["check"])
    sys.exit(rc)
