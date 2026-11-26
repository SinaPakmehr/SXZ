# Security policy

SXZ is experimental research software, not a production or security-critical
system. It is not hardened for untrusted archives, hostile inputs, or
multi-tenant services. Checksums detect accidental corruption; they do not
authenticate data. Use an isolated, resource-limited process for experimental
decoders and never run downloaded benchmark executables.

## Reporting

Do not disclose a vulnerability publicly. Once the public repository is
created, use its **Security** tab and GitHub Private Vulnerability Reporting
at <https://github.com/SinaPakmehr/SXZ/security/advisories/new> to send a
confidential report with a minimal reproduction and affected component. The
private reporting feature must be enabled and verified by the maintainer before
this policy is considered operational.

Until that interface is enabled, no public vulnerability channel should be
claimed. Do not attach malicious samples, credentials, or private data to a
public issue.
