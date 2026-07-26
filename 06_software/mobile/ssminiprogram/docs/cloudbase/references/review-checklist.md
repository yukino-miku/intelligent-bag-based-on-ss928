# Review Checklist

## Project and routing

- [ ] Read repository instructions and current `work/ssminiprogram` code.
- [ ] Confirmed `project.config.json`, AppID presence, and `miniprogramRoot`.
- [ ] Preserved both BLE and cloud capabilities.
- [ ] Did not mix Web SDK or Web login patterns into native Mini Program code.

## Mini Program

- [ ] `wx.cloud.init` runs once with an explicit canonical EnvId.
- [ ] Pages consume normalized service objects rather than raw transport payloads.
- [ ] `wx.cloud.callFunction` is used for privileged/identity-aware operations.
- [ ] Direct database access is limited by appropriate collection rules.
- [ ] Loading, empty, offline, timeout, permission, and stale-data states are handled.
- [ ] Track and alarm lists use pagination.

## Cloud Functions

- [ ] Correctly selected Event Function or HTTP Function.
- [ ] HTTP Function listens on port `9000` and includes `scf_bootstrap`.
- [ ] Routes, methods, content type, body parsing, and status codes are explicit.
- [ ] Target collections exist before runtime writes.
- [ ] Server-side validation rejects malformed or oversized input.
- [ ] Logs do not contain secrets or complete sensitive payloads.

## User authorization

- [ ] OPENID comes from `cloud.getWXContext()`, not client input.
- [ ] Device access is checked through a binding/authorization record.
- [ ] Unauthorized users cannot query another device by changing `deviceId`.

## Device security

- [ ] Device upload uses HTTPS.
- [ ] Device identity uses a per-device credential.
- [ ] Signature covers method, path, timestamp, nonce, and exact body hash.
- [ ] Stale timestamps and replayed nonces are rejected.
- [ ] Secrets are outside Git and client code.
- [ ] Rate and payload limits are defined.

## Data model

- [ ] Latest state is separate from append-only track/alarm history.
- [ ] Server receive time is stored.
- [ ] Coordinates and numeric sensor values are range-checked and finite.
- [ ] Collection indexes match actual query order.
- [ ] History retention or cleanup policy is documented.

## Deployment and evidence

- [ ] Canonical EnvId confirmed before changes.
- [ ] MCP schema or `tcb --help` checked before management commands.
- [ ] Existing resources preserved; destructive actions explicitly approved.
- [ ] Deployment verified by list/detail/log output.
- [ ] BLE regression test passed.
- [ ] Valid upload, invalid signature, replay, authorized read, and unauthorized read were tested.
- [ ] README states what is implemented, deployed, simulated, and pending hardware validation.
