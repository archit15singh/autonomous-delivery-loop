# Dagger TypeScript SDK Node compatibility

| Check | Upstream base | Candidate |
| --- | --- | --- |
| SDK's declared Node requirement | Node 20 and newer | Same Node range as its locked GraphQL dependency |
| Node 20.20.2 | SDK accepts the version, then Yarn rejects GraphQL | Yarn rejects the SDK package during manifest validation |
| Node 23.11.1 | Advertised by the SDK's range | Yarn rejects the SDK package during manifest validation |
| Node 22.23.5 and 24.22.3 | CI already uses Node 22 | Frozen install, SDK build, authenticated GraphQL request and package creation pass |

The existing provisioning workflow already moved to Node 22. This patch updates the remaining package metadata. The tested package tarballs from both supported versions advertise the same range as the locked GraphQL dependency. [Previous CI fix](https://github.com/dagger/dagger/pull/13680)

The hosted jobs ran Yarn 1.22.22 with `--frozen-lockfile`, compiled the candidate with `yarn build`, sent a GraphQL query with the real built SDK client to a loopback server, and ran `npm pack`. The HTTP fixture verifies the request path, query, and authorization. Full Dagger engine provisioning and Node 25 or later were outside this replay.

- Base `c1f8e9ae88f6c238ee02bef12ff131847052abc2`. [Node 20 baseline](https://github.com/archit15singh/autonomous-delivery-loop/actions/runs/44858853096)
- Candidate `6173169373d078cbb366e5c39cf80ed9b76332ff`. [Commit](https://github.com/archit15singh/dagger/commit/6173169373d078cbb366e5c39cf80ed9b76332ff) · [Four hosted jobs and package artifacts](https://github.com/archit15singh/autonomous-delivery-loop/actions/runs/44859106371)
- [Upstream issue](https://github.com/dagger/dagger/issues/13610)
