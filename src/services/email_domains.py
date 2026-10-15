"""
Aevus -- email normalization and business vs free-mail domain classification.

Door 1 (gated synthetic demo) auto-provisions only for business email domains.
Free-mail (and disposable) domains are held for a human to approve. The gate is a
lead-quality filter, NOT a security boundary: the demo is synthetic-only, so a
business-looking domain an attacker controls gains nothing real. The safe error
direction is "treat as free-mail" (a human looks), so the heuristics below lean
that way.
"""

from __future__ import annotations

import re
from typing import Final

# Pragmatic address check (RFC 5322 is far wider than any real prospect needs).
# No whitespace/control characters, which also blocks header-injection payloads.
_EMAIL_RE: Final = re.compile(
    r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$"
)
MAX_EMAIL_LEN: Final = 254

# Exact free-mail / consumer ISP domains. Matched as the domain itself or any
# subdomain of it.
FREE_MAIL_DOMAINS: Final[frozenset[str]] = frozenset(
    {
        # Google
        "gmail.com",
        "googlemail.com",
        # Microsoft
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "passport.com",
        # Yahoo / Verizon / AT&T family
        "yahoo.com",
        "ymail.com",
        "rocketmail.com",
        "aol.com",
        "aim.com",
        "verizon.net",
        "sbcglobal.net",
        "att.net",
        "bellsouth.net",
        "pacbell.net",
        "swbell.net",
        "ameritech.net",
        "flash.net",
        "prodigy.net",
        # Apple
        "icloud.com",
        "me.com",
        "mac.com",
        # Privacy mail
        "proton.me",
        "protonmail.com",
        "pm.me",
        "tutanota.com",
        "tuta.io",
        "tutamail.com",
        "hushmail.com",
        "mailfence.com",
        # Cable / telco ISPs
        "comcast.net",
        "xfinity.com",
        "cox.net",
        "charter.net",
        "spectrum.net",
        "earthlink.net",
        "windstream.net",
        "frontier.com",
        "centurylink.net",
        "embarqmail.com",
        "optonline.net",
        "roadrunner.com",
        "twc.com",
        "suddenlink.net",
        "sky.com",
        "btinternet.com",
        # Other consumer mail
        "gmx.com",
        "gmx.net",
        "gmx.us",
        "mail.com",
        "email.com",
        "zoho.com",
        "zohomail.com",
        "yandex.com",
        "yandex.ru",
        "mail.ru",
        "inbox.com",
        "fastmail.com",
        "fastmail.fm",
        "qq.com",
        "163.com",
        "126.com",
        "naver.com",
        "web.de",
        "libero.it",
        "rediffmail.com",
        "cock.li",
        "duck.com",
        "hey.com",
        # Disposable / throwaway
        "mailinator.com",
        "guerrillamail.com",
        "10minutemail.com",
        "tempmail.com",
        "temp-mail.org",
        "yopmail.com",
        "trashmail.com",
        "sharklasers.com",
        "getnada.com",
        "dispostable.com",
        "maildrop.cc",
        "throwawaymail.com",
    }
)

# Consumer brands that ship many country domains (yahoo.co.uk, hotmail.fr,
# outlook.de, live.nl ...). A short domain whose first label is one of these is
# treated as free-mail without enumerating every ccTLD.
_FREE_MAIL_BRAND_LABELS: Final[frozenset[str]] = frozenset(
    {"yahoo", "hotmail", "outlook", "live", "gmail", "googlemail", "msn", "aol", "icloud", "proton", "protonmail"}
)


_GENERIC_SLDS: Final[frozenset[str]] = frozenset({"co", "com", "net", "org", "ne", "or", "ac"})


class InvalidEmailError(ValueError):
    """Raised when an address fails normalization/validation."""


def normalize_email(raw: str) -> str:
    """Return the lowercased, stripped address or raise InvalidEmailError."""
    if not isinstance(raw, str):
        raise InvalidEmailError("email must be a string")
    email = raw.strip().lower()
    if not email or len(email) > MAX_EMAIL_LEN or not _EMAIL_RE.match(email):
        raise InvalidEmailError("invalid email address")
    return email


def email_domain(email: str) -> str:
    """Return the domain part of an already-normalized address."""
    return email.rsplit("@", 1)[1]


def is_free_mail_domain(domain: str) -> bool:
    """True if `domain` is a free-mail, consumer-ISP, or disposable provider."""
    d = domain.strip().lower().rstrip(".")
    if d in FREE_MAIL_DOMAINS or any(d.endswith("." + f) for f in FREE_MAIL_DOMAINS):
        return True
    labels = d.split(".")
    if labels[0] not in _FREE_MAIL_BRAND_LABELS:
        return False
    # hotmail.fr (2 labels) or yahoo.co.uk / yahoo.com.br (brand + generic SLD + ccTLD).
    # outlook.acme.com is a company's own subdomain and is not matched.
    return len(labels) == 2 or (len(labels) == 3 and labels[1] in _GENERIC_SLDS and len(labels[2]) == 2)


def classify_email(email: str) -> str:
    """Classify a normalized address as ``"business"`` or ``"free_mail"``."""
    return "free_mail" if is_free_mail_domain(email_domain(email)) else "business"
