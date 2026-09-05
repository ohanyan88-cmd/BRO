"""Whose word BRO may study, and what that word is worth.

Discovery finds candidates. This module decides what a candidate may become, and it is the
only thing that decides. The separation matters because a system that can classify its own
new sources can eventually classify anything as authoritative -- so an unclassified host
stays a candidate awaiting a person, and BRO never promotes one.

Authority here is always scoped. The RFC Editor is authoritative for the RFC it published
and about nothing else, and no tier makes external material outrank BRO's own contracts,
governance or current runtime truth.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit


class SourcePolicyRejected(RuntimeError):
    pass


class AuthorityTier(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    UNCLASSIFIED = "UNCLASSIFIED"


@dataclass(frozen=True)
class SourceFamily:
    family: str
    tier: AuthorityTier
    publisher: str
    scope: str
    hosts: tuple[str, ...]
    entry_points: tuple[str, ...] = ()
    authority_class: str = "TRUSTED_REFERENCE"
    admissible: bool = True
    note: str = ""


@dataclass(frozen=True)
class HostVerdict:
    """What the policy says about one host, and why."""

    host: str
    tier: AuthorityTier
    family: str
    publisher: str
    scope: str
    admissible: bool
    auto_admit: bool
    authority_class: str
    may_produce_verified_knowledge: bool
    reason: str

    @property
    def is_classified(self) -> bool:
        return self.tier is not AuthorityTier.UNCLASSIFIED


# Query parameters that identify a visitor rather than a document. Stripping them is what
# makes two links to the same page deduplicate instead of being fetched twice.
TRACKING_PARAMETERS = (
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "ref", "ref_src", "s", "mc_cid", "mc_eid",
)
DEFAULT_PORTS = {"https": "443", "http": "80"}


def canonical_url(url: str) -> str:
    """One spelling per document, so the frontier can tell repeats from new pages.

    Lowercases scheme and host, drops the default port, drops the fragment, removes
    tracking parameters, and collapses an empty path to "/". It never changes which
    document is addressed.
    """
    parts = urlsplit(str(url or "").strip())
    if not parts.scheme or not parts.netloc:
        raise SourcePolicyRejected(f"not an absolute url: {url!r}")
    host = parts.hostname or ""
    if not host:
        raise SourcePolicyRejected(f"url carries no host: {url!r}")
    scheme = parts.scheme.lower()
    netloc = host.lower()
    if parts.port and str(parts.port) != DEFAULT_PORTS.get(scheme, ""):
        netloc = f"{netloc}:{parts.port}"
    kept = [
        pair for pair in parts.query.split("&")
        if pair and pair.split("=", 1)[0].lower() not in TRACKING_PARAMETERS
    ]
    return urlunsplit((scheme, netloc, parts.path or "/", "&".join(kept), ""))


def host_of(url: str) -> str:
    host = urlsplit(str(url or "").strip()).hostname
    if not host:
        raise SourcePolicyRejected(f"url carries no host: {url!r}")
    return host.lower()


def _matches(host: str, declared: str) -> bool:
    """A family claims a host and everything under it, and nothing that merely ends the same.

    ``evil-nist.gov`` is not ``nist.gov``, and refusing to notice that is how an allowlist
    stops being one.
    """
    host = host.lower().rstrip(".")
    declared = declared.lower().rstrip(".")
    return host == declared or host.endswith("." + declared)


class SourcePolicy:
    """The governed answer to: may BRO study this, and how far may it believe it."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        self.document = dict(document)
        self.tiers = dict(self.document.get("tiers", {}))
        if not self.tiers:
            raise SourcePolicyRejected("a source policy must declare its tiers")
        self.families = tuple(
            SourceFamily(
                family=str(entry["family"]),
                tier=AuthorityTier(entry["tier"]),
                publisher=str(entry["publisher"]),
                scope=str(entry["scope"]),
                hosts=tuple(str(host).lower() for host in entry["hosts"]),
                entry_points=tuple(str(url) for url in entry.get("entry_points", ())),
                authority_class=str(entry.get("authority_class", "TRUSTED_REFERENCE")),
                admissible=bool(entry.get("admissible", True)),
                note=str(entry.get("note", "")),
            )
            for entry in self.document.get("families", ())
        )
        self.denied_hosts = tuple(str(h).lower() for h in self.document.get("denied_hosts", ()))
        self.discovery_only_hosts = tuple(
            str(h).lower() for h in self.document.get("discovery_only_hosts", ()))
        self.budgets = dict(self.document.get("budgets", {}))
        self.allowed_content_types = tuple(
            str(t).lower() for t in self.document.get("allowed_content_types", ()))

    @classmethod
    def load(cls, path: str | Path) -> "SourcePolicy":
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            raise SourcePolicyRejected(f"source policy is unreadable: {exc}") from None
        except json.JSONDecodeError as exc:
            raise SourcePolicyRejected(f"source policy is not valid JSON: {exc}") from None
        return cls(document)

    # ----------------------------------------------------------------- classification
    def classify(self, url: str) -> HostVerdict:
        """Name the tier of the host this url addresses, and what follows from it."""
        host = host_of(url)
        for denied in self.denied_hosts:
            if _matches(host, denied):
                return self._verdict(host, AuthorityTier.UNCLASSIFIED, "denied", "", "",
                                     admissible=False,
                                     reason=f"{host} is on the policy's denied list")
        for family in self.families:
            if any(_matches(host, declared) for declared in family.hosts):
                rule = self.tiers.get(family.tier.value, {})
                return HostVerdict(
                    host=host, tier=family.tier, family=family.family,
                    publisher=family.publisher, scope=family.scope,
                    admissible=family.admissible, authority_class=family.authority_class,
                    auto_admit=bool(rule.get("auto_admit")) and family.admissible,
                    may_produce_verified_knowledge=bool(
                        rule.get("may_produce_verified_knowledge")),
                    reason=(family.note or
                            f"{host} belongs to the {family.family} family, tier {family.tier.value}"),
                )
        for lead in self.discovery_only_hosts:
            if _matches(host, lead):
                rule = self.tiers.get("D", {})
                return HostVerdict(
                    host=host, tier=AuthorityTier.D, family="discovery-only",
                    publisher="", scope="candidate leads only", admissible=False,
                    auto_admit=False, authority_class="TRUSTED_REFERENCE",
                    may_produce_verified_knowledge=bool(
                        rule.get("may_produce_verified_knowledge")),
                    reason=f"{host} is a discovery-only host: it may suggest, never testify",
                )
        return self._verdict(host, AuthorityTier.UNCLASSIFIED, "unclassified", "", "",
                             admissible=False,
                             reason=f"no family claims {host}; it stays a candidate for a person")

    def _verdict(self, host: str, tier: AuthorityTier, family: str, publisher: str, scope: str,
                 *, admissible: bool, reason: str) -> HostVerdict:
        rule = self.tiers.get(tier.value, {})
        return HostVerdict(
            host=host, tier=tier, family=family, publisher=publisher, scope=scope,
            admissible=admissible, auto_admit=False, authority_class="TRUSTED_REFERENCE",
            may_produce_verified_knowledge=bool(rule.get("may_produce_verified_knowledge")),
            reason=reason,
        )

    # ------------------------------------------------------------------- permissions
    def may_acquire(self, url: str) -> HostVerdict:
        """Acquisition is allowed one step wider than admission: a tier-D lead may be read
        as a lead. It still cannot enter the corpus, and it still cannot testify."""
        verdict = self.classify(url)
        if verdict.tier is AuthorityTier.UNCLASSIFIED:
            raise SourcePolicyRejected(verdict.reason)
        return verdict

    def may_admit(self, url: str) -> HostVerdict:
        verdict = self.classify(url)
        if not verdict.admissible:
            raise SourcePolicyRejected(
                f"policy does not admit {verdict.host} to the study corpus: {verdict.reason}")
        return verdict

    def entry_points(self, *, tiers: tuple[AuthorityTier, ...] = ()) -> tuple[str, ...]:
        """Where discovery is allowed to start. Never a search engine, always a policy host."""
        wanted = set(tiers) or {AuthorityTier.A, AuthorityTier.B, AuthorityTier.C}
        return tuple(url for family in self.families if family.tier in wanted
                     for url in family.entry_points)

    def budget(self, name: str, default: int | float) -> int | float:
        value = self.budgets.get(name, default)
        try:
            number = type(default)(value)
        except (TypeError, ValueError):
            return default
        return number if number > 0 else default

    def content_type_allowed(self, content_type: str) -> bool:
        return str(content_type or "").lower().split(";")[0].strip() in self.allowed_content_types
