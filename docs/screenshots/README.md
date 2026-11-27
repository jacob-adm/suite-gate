# Screenshots

Rendered by `scripts/screenshots.py` from the real output of these versions:

- git-surface 0.4.0
- trust-path 0.8.1
- git-overlap 0.7.0
- release-drift 0.7.0
- glassbox 0.5.1

- [git-surface.svg](git-surface.svg): `printf 'feature/triage-bot\nfix/login-typo\n' | git surface main`
- [git-surface-audit-json.svg](git-surface-audit-json.svg): `echo feature/triage-bot | git surface --audit-json main`
- [trust-path.svg](trust-path.svg): `trust-path --ref feature/triage-bot .`
- [trust-path-audit-json.svg](trust-path-audit-json.svg): `trust-path --ref feature/triage-bot --audit-json .`
- [git-overlap.svg](git-overlap.svg): `printf 'feature/triage-bot\nfix/login-typo\n' | git footprint main | git overlap`
- [git-overlap-audit-json.svg](git-overlap-audit-json.svg): `printf 'feature/triage-bot\nfix/login-typo\n' | git footprint main | git overlap --audit-json`
- [release-drift.svg](release-drift.svg): `release-drift diff demo_lib-1.0.0-py3-none-any.whl demo_lib-1.0.1-py3-none-any.whl`
- [release-drift-audit-json.svg](release-drift-audit-json.svg): `release-drift diff --audit-json demo_lib-1.0.0-py3-none-any.whl demo_lib-1.0.1-py3-none-any.whl`
- [glassbox-persist.svg](glassbox-persist.svg): `glassbox persist --home ~ --since before.json`
