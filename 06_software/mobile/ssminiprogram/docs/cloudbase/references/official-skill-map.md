# Official Tencent CloudBase Skill Map

Source reviewed: `TencentCloudBase/skills`, which listed 28 skills in its README on 2026-07-15.

Use this map to avoid loading all official skills for every task.

## Directly relevant to this project

| Official skill | Use in SS928 smart-backpack work |
|---|---|
| `cloudbase-guidelines` | Main CloudBase routing, management, and deployment guardrails. |
| `miniprogram-development` | Native Mini Program project shape, DevTools, preview, publish, and CloudBase integration entry. |
| `cloud-functions` | Event Functions for Mini Program calls and HTTP Functions for SS928 HTTPS uploads. |
| `auth-wechat` | Native automatic Mini Program identity and `OPENID` handling. |
| `no-sql-wx-mp-sdk` | Client-safe document database queries, pagination, aggregation, geolocation, and rules. |
| `cloudbase-cli` | `tcb` fallback or preferred terminal path when MCP is unavailable or not desired. |
| `cloudbase-code-review` | Final CloudBase misuse and security review. |
| `cloudbase-platform` | Platform concepts, resource selection, and cross-cutting safety protocols. |
| `spec-workflow` | Requirements/design/task planning for multi-module BLE + cloud changes. |
| `ops-inspector` | Function logs and resource-health diagnosis after deployment. |

## Conditionally relevant

| Official skill | Load only when |
|---|---|
| `http-api` | Calling official CloudBase platform APIs over raw HTTP. Do not confuse it with building the project's own device HTTP endpoint. |
| `cloudrun-development` | Long-lived services, WebSocket, MQTT broker, arbitrary runtime, or persistent container behavior is required. |
| `auth-tool` | Configuring identity providers or platform-side auth readiness. Native Mini Program OPENID alone usually does not require it. |
| `auth-nodejs` | A Node backend must inspect or bridge CloudBase user identities outside the standard Mini Program function path. |
| `cloud-storage-web` | A browser Web app needs CloudBase storage. It is not the primary Mini Program storage guide. |
| `data-model-creation` | Legacy complex model tooling is explicitly needed; the official repository marks it deprecated. |
| `postgresql-development` | The project deliberately selects CloudBase PostgreSQL instead of the current document-database design. |
| `relational-database-tool` | Legacy MySQL management is deliberately selected; the official repository marks it deprecated for new environments. |
| `relational-database-web` | Legacy Web relational-database client work is deliberately selected. |
| `cloudbase-wechat-integration` | WeChat Pay, Official Account OAuth, or Integration Center generated payment functions are requested. |
| `ui-design` | The task is interface design rather than cloud/data integration. |
| `ai-model-wechat` | The Mini Program adds CloudBase AI model calls. |
| `ai-model-nodejs` | A Node backend adds model calls or image generation. |
| `cloudbase-agent` | The project adds an AI agent server and AG-UI protocol. |

## Not relevant to the current native Mini Program IoT path

| Official skill | Reason |
|---|---|
| `ai-model-web` | Browser/Web model integration, not native Mini Program telemetry. |
| `auth-web` | Web authentication, not native Mini Program identity. |
| `no-sql-web-sdk` | Browser Web SDK, not `wx.cloud.database()`. |
| `web-development` | React/Vue/browser frontend development, not native Mini Program. |
| `relational-database-web` | Browser relational database path, and deprecated for new environments. |

## Extraction rules used for this custom skill

Retain:

- platform/runtime boundaries
- Mini Program native identity rules
- Event Function vs HTTP Function distinction
- explicit collection creation and permission rules
- MCP/CLI resource-management workflows
- post-implementation review and verification

Add project-specific rules:

- BLE and cloud are both mandatory
- SS928 uses HTTPS rather than `wx.cloud`
- per-device authentication and replay protection
- GNSS, IMU, risk, alarms, and latest-state/history schemas
- data-source abstraction between pages and transports

Exclude:

- AI model integration
- Web frontend stacks
- payment and Official Account flows
- deprecated relational-database defaults
- generic UI design guidance already covered by other project skills
