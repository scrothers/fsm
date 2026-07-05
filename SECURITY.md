# Security Policy

## Supported versions

factorio-server-manager follows [Semantic Versioning](https://semver.org). Security
fixes are applied to the latest released minor version.

| Version | Supported |
| ------- | --------- |
| 1.0.x   | yes       |
| < 1.0   | no        |

## Reporting a vulnerability

Please report security vulnerabilities **privately** — do not open a public issue.

- Preferred: GitHub private vulnerability reporting —
  <https://github.com/scrothers/fsm/security/advisories/new>
- Or email <steven@scrothers.com>.

Include a description, the affected version(s), reproduction steps, and the
impact. You can expect an acknowledgement within 3 business days and a status
update within 7 days. Please practice coordinated disclosure: give us reasonable
time to release a fix before any public disclosure.

## Scope

This tool manages Factorio servers via systemd, ssh/rsync, and the Factorio mod
portal. Security-relevant areas include:

- Credential handling — the mod service token and RCON / game passwords (written
  mode 600; instance YAML git-ignored).
- The ssh/rsync deployer (`fsm-deploy`).
- Mod and game-build downloads (SHA-1 verified, over HTTPS, first-party hosts).
- Generated systemd units and instance configuration.

Out of scope: vulnerabilities in Factorio itself, third-party mods, or the host
operating system.
