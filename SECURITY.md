# Security Policy

TeamMural is designed for private internal communication. Security fixes target the current main branch.

- Use a strong SECRET_KEY and a unique administrator password in production.
- Run behind HTTPS and set COOKIE_SECURE=1 and FORCE_HTTPS=1.
- Never commit databases, uploads, real chat exports or credentials.
- Attachments are authorized against channel membership before serving.
- User-created content is rendered as text; avoid adding raw HTML rendering paths.
- SQLite is suitable for a small single-instance deployment. Use PostgreSQL/object storage before scaling to multiple workers or replicas.

Report vulnerabilities privately through GitHub Security Advisories / Private Vulnerability Reporting when available.
