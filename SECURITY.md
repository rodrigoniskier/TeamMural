# Security

This public portfolio edition contains synthetic records only. Report vulnerabilities privately through GitHub security advisories; never post credentials or private data in issues.

`PORTFOLIO_DEMO=1` must use an isolated database. Public demo identities are deliberately unprivileged. Admin access and unrestricted uploads are disabled. Inputs remain untrusted; CSRF protection and authorization still apply.

Deployment secrets belong only in the hosting platform environment. Use a unique random `SECRET_KEY`, PostgreSQL with TLS, exact allowed hosts and HTTPS cookies. Never reuse a production database for this demo.

This bounded demonstration does not provide production-grade abuse prevention. Shared demo content is visible to visitors and must not contain personal or confidential information.
