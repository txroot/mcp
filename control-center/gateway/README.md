# Gateway provider inventory candidate

This directory contains Gateway-side candidate code. It is not installed by the Control Center installer and is not deployed to production by CI.

## Tool

`provider_inventory.py` registers one read-only MCP tool:

```text
gateway_provider_inventory
```

The tool uses the same `READ_ONLY_LOCAL` annotation contract as `gateway_health`, `gateway_vm_status` and other local read-only Gateway tools.

It returns only a minimized operational projection:

- canonical domain and provider identity;
- runtime kind and canonical runtime target;
- whether the component is exposed by the Gateway;
- readiness as `healthy`, `degraded`, `unhealthy` or `unknown`;
- the symbolic status contract used as evidence;
- lifecycle state.

It does not return provider credentials, OAuth scopes, token IDs, paths to credentials, full readiness documents, graph fingerprints, Vault paths, stack traces or arbitrary exception text.

## Resolver boundary

`provider_inventory_resolvers.py` contains the closed mapping between canonical component identities and existing read-only Gateway status tools.

Current reconciliation contains 26 provider components:

- 24 have an explicit read-only resolver;
- `prestashop/product-description-write` remains intentionally `unknown` because no canonical status tool exists yet;
- `trello/readwrite` remains intentionally `unknown` because Trello is healthy on its Unix socket but is not yet exposed through the Gateway tool inventory.

Examples:

```text
mail/read                     -> mail.read.status
mail/send                     -> mail.send.status
calendar/read                 -> calendar.read.status
sheets/write                  -> sheets.write.status
prestashop/category-writer    -> prestashop.category_writer.status
pc-edge/pc-edge-provider      -> pc.health
```

The mapping is static code. Inventory data cannot choose a tool dynamically. A mismatch between the canonical inventory and the resolver mapping fails closed.

`provider_status_client.py` is the canary-only status client. It can call only the exact read-only status tools present in the static resolver map, accepts no arguments, requires HTTP loopback `/mcp`, limits response size and does not propagate remote error text.

Missing resolvers produce `unknown`; they never become healthy by default. Resolver failures are reduced to the exception class only.

## Registration pattern

The production Gateway integration remains intentionally small:

```python
register_gateway_provider_inventory(
    server,
    annotations=READ_ONLY_LOCAL,
    inventory=runtime_inventory,
    status_resolvers=status_resolvers,
    audit=_audit,
)
```

The resulting audit event is `PROVIDER_INVENTORY_READ` with only inventory ID, domain/provider counts and `external_effect=false`.

## Reproducible canary overlay

`canary/apply_overlay.py` applies the provider-inventory candidate to a copy of the current Gateway runtime. It fails unless the expected production `server.py` import and return anchors match exactly, and it refuses a second application.

The overlay copies only:

```text
provider_inventory.py
provider_inventory_resolvers.py
provider_status_client.py
provider_inventory_smoke.py
sofia_runtime_inventory.py
sofia-os-provider-inventory.json
```

and patches `server.py` to register `gateway_provider_inventory` before `create_mcp_server()` returns.

## Isolated canary build

`canary/build_smoke_canary.sh` is designed to run on `eletrix-server` after explicit authorization.

It deliberately does **not** replace or restart `pedrovault-mcp-production`:

1. verifies the production container is running and healthy;
2. resolves the exact production image currently in use;
3. copies only `server.py` to a temporary build context;
4. applies the reproducible overlay;
5. builds a derivative image tagged `provider-inventory-canary-<git-sha>`;
6. imports the patched Gateway server in a transient container;
7. runs `provider_inventory_smoke.py` in a second transient container using host networking only to reach the production Gateway read-only status endpoint at `127.0.0.1:8770/mcp`;
8. exits without leaving a running canary container.

The smoke check requires exactly:

```text
13 domains
26 provider components
24 explicit read-only resolvers
0 lifecycle actions
```

It prints only the minimized inventory summary and the two intentionally unresolved component IDs. It never prints raw provider readiness documents.

The canary build creates a local Docker image as a test artefact. Promotion of that image is a separate, explicitly controlled operation.

## Lifecycle boundary

The reconciled inventory requires `lifecycle_enabled=false` for every component. The provider inventory tool cannot enable lifecycle and returns an empty action list for every provider.

Lifecycle will only be designed after canonical provider identities and live readiness have been proven in the Gateway.

## Production activation gate

Before this candidate can be installed in the Sofia OS Gateway production image:

1. build and run the isolated canary successfully;
2. inspect the minimized readiness summary and investigate any unexpected `unhealthy` result;
3. keep Trello and product-description status as `unknown` until canonical probes exist;
4. expose `gateway_provider_inventory` only in the canary first;
5. compare the canary inventory with the reconciled 13-domain baseline;
6. verify lifecycle remains disabled;
7. verify the production Gateway container, tunnel and broker were untouched by the canary exercise;
8. only then prepare a separate promotion plan with rollback and audit.
