# Deployment and Security

## Contents

1. MCP and CLI boundary
2. Environment handling
3. Function exposure
4. User authorization
5. Device authentication
6. Secret handling
7. Deployment evidence

## 1. MCP and CLI boundary

MCP is a management interface, not an application protocol.

- The Mini Program does not need MCP at runtime.
- SS928 does not need MCP at runtime.
- Codex can write source code without MCP.
- An agent needs MCP, `tcb` CLI, WeChat DevTools, or console access to create/deploy resources and inspect live state.

Official CloudBase guidance prefers MCP for IDE-integrated resource management. The official `cloudbase-cli` skill also supports `tcb` for deployment, database, permissions, CORS, and other terminal-managed tasks.

Use the available management path and report limitations honestly.

## 2. Environment handling

- Use the canonical full EnvId.
- Never guess an EnvId from a nickname.
- Initialize the Mini Program once:

```javascript
wx.cloud.init({
  env: "canonical-env-id",
  traceUser: true,
});
```

- In Event Functions, use:

```javascript
cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });
```

- Keep development and production environments separate when the project grows beyond a single competition environment.

## 3. Function exposure

### Event Function

Use for `wx.cloud.callFunction` and trusted WeChat caller identity.

### HTTP Function

Use for SS928 uploads. An HTTP Function is a standard service process that listens on port `9000`; it is not an `exports.main` handler.

Public access must be intentional. Configure the function security rule/gateway, then enforce device authentication inside the function.

Return:

- `200` or `202` for accepted data
- `400` for malformed schema
- `401` for missing/invalid device credentials
- `403` for disabled or unauthorized device
- `409` for replayed nonce or duplicate alarm ID
- `413` for excessive payload
- `429` for rate limiting
- `500` only for unexpected server failures

Do not leak stack traces or secrets in responses.

## 4. User authorization

Mini Program native CloudBase identity is automatic. Do not build a Web OAuth login page.

Inside an Event Function:

```javascript
const { OPENID } = cloud.getWXContext();
```

Before returning device data, verify that `OPENID` has an enabled binding to the requested `deviceId`. Do not rely on a `deviceId` supplied by the client alone.

## 5. Device authentication

Recommended competition-ready minimum:

- per-device secret
- timestamp
- nonce
- HMAC-SHA256 signature
- short clock-skew window
- replay prevention
- request-size and rate limits

For production, add secret rotation, provisioning, revocation, audit logs, and secure hardware storage where available.

A TLS connection protects data in transit but does not identify the device by itself.

## 6. Secret handling

Never commit:

- Tencent SecretId/SecretKey
- CloudBase administrator API keys
- device HMAC secrets
- database credentials
- private certificates

Use function environment variables or a secrets-management facility. Put local secret files in `.gitignore`. Redact credentials from screenshots and logs.

A publishable key is not a substitute for per-device authentication.

## 7. Deployment evidence

Before claiming completion, record:

- canonical EnvId
- function type and deployed function name
- verified invocation URL for HTTP Function
- configured function access rule
- collection names and indexes
- collection permission rules
- a successful signed upload result
- a rejected invalid-signature result
- a successful authorized Mini Program read
- log location and timestamp

When the current environment cannot deploy, provide exact manual steps and mark the deployment as pending.
