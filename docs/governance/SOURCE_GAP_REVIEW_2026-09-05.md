# Source-gap governance review — 2026-09-05

Six curriculum requirements have no admitted publisher. This reviews each one before any
policy change, because admitting a host is granting a publisher the right to produce
VERIFIED durable knowledge, and the reason the curriculum reports gaps by name instead of
resolving them is that the decision is not the runtime's to take.

Nothing in this document changes `contracts/source_policy.json`. Every fact below was
fetched on 2026-09-05 and the command output is what is reported.

---

## 1. `kernel.org` — linux.kernel-documentation

**Publisher.** The Linux Kernel Organization. `https://www.kernel.org/doc/html/latest/`
answers 200 and titles itself *The Linux Kernel documentation*; it is rendered from the
`Documentation/` tree of the kernel source itself. `docs.kernel.org` serves the same tree.

**Primary or canonical.** Primary. This is the kernel project documenting the kernel — the
same relationship `doc.rust-lang.org` has to Rust and `docs.python.org` to CPython, both
already tier A.

**Requirement closed.** `linux.kernel-documentation`, and see §2 for the second one.

**Recommended tier.** **A**, new family `linux-kernel`, hosts `kernel.org`,
`www.kernel.org`, `docs.kernel.org`.

**Recommendation: ADMIT.**

---

## 2. `man7.org` — linux.syscall-interface

**Publisher.** Michael Kerrisk's domain. `https://man7.org/linux/man-pages/man2/syscalls.2.html`
answers 200 and renders *syscalls(2) — Linux manual page*.

**Primary or canonical.** Neither, and this is the whole finding. The Linux man-pages
project's own home is `https://www.kernel.org/doc/man-pages/` (200), which links out to
`man7.org/linux/man-pages/index.html` under the label **"online pages"**. So man7.org is the
project's designated rendering host, not a random mirror — but designation is not
publication, and the project's canonical home is on kernel.org.

**The reason not to admit it anyway.** The policy matches hosts, not paths. Admitting
`man7.org` admits the entire site — a book, training courses, a blog — on the strength of
one directory the man-pages project points at. The requirement does not need it:
`https://www.kernel.org/doc/html/latest/userspace-api/index.html` answers 200 and is the
kernel's own documentation of the userspace interface, which is what
`linux.syscall-interface` asks for.

**Recommendation: DO NOT ADMIT.** Re-declare `linux.syscall-interface` against
`kernel.org/doc/html/latest/userspace-api/`, which §1 already admits. Revisit only if the
requirement turns out to need per-syscall pages that the kernel tree does not render, and
then only with path scoping the policy does not have today.

---

## 3. `sre.google` — sre.service-objectives

**Publisher.** `https://sre.google/sre-book/service-level-objectives/` answers 200 and
carries **"© 2017 Google, Inc. Published by O'Reilly Media, Inc."**

**Primary or canonical.** For Google's own practice, yes. For the subject, no. This is one
company's book about how that company runs its services. There is no standards body behind
service-level objectives and error budgets, and the material is nine years old.

**Recommended tier.** **C — PROVEN_ENGINEERING** at best, and tier C is `auto_admit: false`
in the policy: the family would have to be marked admissible by hand, which is a second
deliberate act, not a consequence of adding the host.

**Recommendation: DO NOT ADMIT.** Leave `sre.service-objectives` an honest SOURCE_GAP. A
curriculum that reports "no admitted authority defines this" is telling the truth; importing
one vendor's book as the authority on reliability would make BRO's verified knowledge about
SLOs an account of Google's practice while reading as a statement about the field. If the
requirement must close, the better move is to re-declare it against material an admitted
standards publisher actually covers, and I have not found one.

---

## 4. `opentelemetry.io` — obs.telemetry-signals

**Publisher.** `https://opentelemetry.io/docs/specs/otel/` answers 200, titles itself
*OpenTelemetry Specification 1.60.0*, and the page carries CNCF attribution.

**Primary or canonical.** Primary. It is the specification of the thing, published by the
project that defines it, under the Cloud Native Computing Foundation.

**Consistency.** `kubernetes.io` is already admitted at tier A with the publisher recorded as
*Cloud Native Computing Foundation*. Admitting OpenTelemetry at a lower tier than Kubernetes
would be inconsistent with a precedent this policy already set.

**Recommended tier.** **A**, new family `opentelemetry`, host `opentelemetry.io`.

**Recommendation: ADMIT.**

---

## 5. `platform.claude.com` — llm.model-documentation, ag.tool-use

**Publisher.** Anthropic. `https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview`
answers 200 and titles itself *Tool use with Claude — Claude Platform Docs*.

**This is not a new publisher.** The policy already admits family `anthropic` at tier A,
publisher *Anthropic*, hosts `docs.anthropic.com` and `code.claude.com`, scope *Claude,
Claude Code and the Agent SDK*. `https://docs.anthropic.com/en/home` now answers 200 at
`https://platform.claude.com/docs/en/home` — the admitted publisher moved its documentation
to a host the policy was never told about. `code.claude.com` still serves on its own host.

**What this means today.** The acquisition boundary follows redirects one hop at a time and
re-checks each hop, so every admitted Anthropic URL is refused at the first hop. The family
is in the allowlist and the path is closed.

**Recommended tier.** **A**, added as a host to the **existing** `anthropic` family. Keep
`docs.anthropic.com` in the list — it redirects, and the hop check will then pass.

**Recommendation: ADMIT** — and this is the one I would do first, because it is not a grant
of new authority at all. It is the allowlist catching up with a publisher it already trusts.

---

## Summary

| # | host | requirement | recommendation | tier |
|---|---|---|---|---|
| 1 | `kernel.org` | linux.kernel-documentation | **ADMIT** — new family `linux-kernel` | A |
| 2 | `man7.org` | linux.syscall-interface | **DO NOT ADMIT** — re-declare against kernel.org | — |
| 3 | `sre.google` | sre.service-objectives | **DO NOT ADMIT** — leave the gap | C at best |
| 4 | `opentelemetry.io` | obs.telemetry-signals | **ADMIT** — new family `opentelemetry` | A |
| 5 | `platform.claude.com` | llm.model-documentation, ag.tool-use | **ADMIT** — host of the existing `anthropic` family | A |

Five of the six gaps close: three by admission, one by re-declaring against a host the first
admission brings in. One stays open on purpose.

Two new families and one host addition. The policy is otherwise unchanged, and no admission
here is inferred from a page's own claim about itself: each publisher's standing comes from
what the project's own canonical home says, or — for Anthropic — from a family the policy
already admits.

**This document is a recommendation. The policy change is the Owner's.**
