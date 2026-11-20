"""Write a small proxy log with today's timestamps: `make sample-log`.

It holds traffic from two teams to a known AI tool and to one AI service the inventory has
never seen. Drop it in `inbox/` (the default) or upload it on the Inventory page.
"""

import sys
import time
from pathlib import Path

UNKNOWN_AI_DOMAIN = "translatix.example"
VISITS = (
    ("e.papadaki", "10.20.1.11", "chatgpt.com", 6),
    ("e.papadaki", "10.20.1.11", UNKNOWN_AI_DOMAIN, 9),
    ("-", "10.20.3.40", UNKNOWN_AI_DOMAIN, 4),
)


def lines(now: float) -> list[str]:
    """Squid native access.log lines, one request a minute going back from `now`."""
    rows: list[str] = []
    for user, address, domain, count in VISITS:
        for index in range(count):
            stamp = now - 60 * (len(rows) + index + 1)
            rows.append(
                f"{stamp:.3f}    142 {address} TCP_TUNNEL/200 {4096 + 512 * index} CONNECT "
                f"{domain}:443 {user} HIER_DIRECT/203.0.113.9 -"
            )
    return rows


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "inbox/sample-proxy.log")
    target.write_text("\n".join(lines(time.time())) + "\n")
    print(f"wrote {target}")
