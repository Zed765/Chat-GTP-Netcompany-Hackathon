"""Made-up credentials in the documented formats of common providers.

They are random strings from a seeded generator and open nothing. No literal credential
appears in this file, so the repository's secret scan has nothing to find here.
"""

import string
from collections.abc import Callable
from random import Random

_UPPER_DIGITS = string.ascii_uppercase + string.digits
_ALNUM = string.ascii_letters + string.digits
_BASE64 = _ALNUM + "+/"


def _pick(rng: Random, alphabet: str, length: int) -> str:
    return "".join(rng.choices(alphabet, k=length))


def aws_access_key_id(rng: Random) -> str:
    return f"AKIA{_pick(rng, _UPPER_DIGITS, 16)}"


def aws_secret_access_key(rng: Random) -> str:
    return _pick(rng, _BASE64, 40)


def github_token(rng: Random) -> str:
    return f"ghp_{_pick(rng, _ALNUM, 36)}"


def stripe_secret_key(rng: Random) -> str:
    return f"sk_live_{_pick(rng, _ALNUM, 24)}"


def slack_bot_token(rng: Random) -> str:
    digits = string.digits
    return f"xoxb-{_pick(rng, digits, 12)}-{_pick(rng, digits, 13)}-{_pick(rng, _ALNUM, 24)}"


def google_api_key(rng: Random) -> str:
    return f"AIza{_pick(rng, _ALNUM + '_-', 35)}"


def openai_api_key(rng: Random) -> str:
    return f"sk-proj-{_pick(rng, _ALNUM, 48)}"


def connection_string(rng: Random) -> str:
    password = _pick(rng, _ALNUM, 18)
    return f"postgresql://billing_app:{password}@db.internal.example:5432/billing"


# Single-line secrets, by the name a template uses for them.
SECRET_MAKERS: dict[str, Callable[[Random], str]] = {
    "aws_key": aws_access_key_id,
    "aws_secret": aws_secret_access_key,
    "github_token": github_token,
    "stripe_key": stripe_secret_key,
    "slack_token": slack_bot_token,
    "google_key": google_api_key,
    "openai_key": openai_api_key,
    "connection_string": connection_string,
}
