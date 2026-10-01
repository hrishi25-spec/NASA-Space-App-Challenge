# Security

Pyro-Harmony is an anonymous prototype console for public NASA FIRMS data: no accounts, no cookies, no stored credentials, and a single in-memory dataset per process. The threat model, the enforced guarantees and the accepted gaps are documented in [README.md § Security notes](README.md#security-notes) — including the URL allowlist for live regions, upload caps applied before buffering, origin-gated writes, sanitised filenames, and the rule that `FIRMS_MAP_KEY` is never accepted from a request and never echoed.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting on this repository (**Security → Report a vulnerability**) rather than a public issue. Include the request or the reproduction that shows the problem, and do not attach real datasets or API keys.

If private reporting is unavailable to you, open a minimal public issue that describes the class of problem without a working exploit and ask for a private channel.

## Supported versions

`main` only. This is a prototype, not a maintained release line — there are no backports.
