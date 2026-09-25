# TeamMural

> **Portfolio edition:** a secure, generic internal communication hub built from a private real-world communication workflow, with all personal context removed.

TeamMural is designed for small teams that need a lightweight private space for group messages, direct conversations and file sharing without the complexity of a large collaboration suite.

## Portfolio snapshot

This project demonstrates authentication, password hashing, CSRF protection, authorization by conversation membership, secure file delivery, uploads, responsive UI and SQLite persistence.

**Stack:** Flask · SQLite · Werkzeug Security · HTML/CSS/JavaScript

## Features

- authenticated user accounts;
- administrator-managed users;
- general team channel;
- private direct messages;
- text messages;
- images, audio, video and generic attachments;
- authorization before reading messages or downloading media;
- CSRF protection for state-changing requests;
- login attempt limiting;
- secure session cookies;
- security headers and CSP;
- health endpoint;
- responsive mobile/desktop interface.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Generate a session key and configure the first administrator in your environment:

```bash
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export TEAMMURAL_ADMIN_EMAIL="admin@example.com"
export TEAMMURAL_ADMIN_PASSWORD="change-this-demo-password"
export TEAMMURAL_ADMIN_NAME="Workspace Admin"
python app.py
```

The administrator is created only when the configured email does not already exist.

## Security model

Selecting a display profile is **not** authentication. TeamMural therefore uses real accounts and server-side sessions. Every channel read, message post and attachment download is checked against channel membership on the backend.

For production, use HTTPS, a persistent `SECRET_KEY`, secure cookies and a managed database/storage layer appropriate to the deployment.

## Origin and privacy

The private communication system that inspired this project remains separate. TeamMural contains no family names, private messages, production database or inherited repository history.
