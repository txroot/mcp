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

The inventory builder does **not** execute a tool named by data from the inventory.

Deployment must provide an explicit Python mapping:

```python
status_resolvers = {
    "sofia-core/gateway": gateway_health_resolver,
    "mail/read": gmail_read_status_resolver,
    "mail/send": gmail_send_status_resolver,
    # ...one explicit resolver per canonical component...
}
```

Keys are canonical component identities (`domain/component`). Missing resolvers produce `unknown`; they never become healthy by default.

A resolver failure is reduced to the exception class only. Exception messages are never copied into the inventory response.

## Registration pattern

The production Gateway integration is intentionally small:

```python
from gateway.provider_inventory import register_gateway_provider_inventory

register_gateway_provider_inventory(
    server,
    annotations=READ_ONLY_LOCAL,
    inventory=runtime_inventory,
    status_resolvers=status_resolvers,
    audit=_audit,
)
```

The resulting audit event is `PROVIDER_INVENTORY_READ` with only inventory ID, domain/provider counts and `external_effect=false`.

## Lifecycle boundary

The reconciled inventory currently requires `lifecycle_enabled=false` for every component. The provider inventory tool cannot enable lifecycle and returns an empty action list for every provider.

Lifecycle will only be designed after canonical provider identities and live readiness have been proven in the Gateway.

## Production activation gate

Before this candidate can be installed in the Sofia OS Gateway image:

1. package the reconciled runtime inventory as immutable Gateway input;
2. wire each canonical component to an explicit existing read-only readiness resolver;
3. confirm no resolver can perform a write or accept arbitrary operation names;
4. run unit/integration tests in a canary Gateway image;
5. compare `gateway_provider_inventory` against the current live provider inventory;
6. verify `PROVIDER_INVENTORY_READ` in the operational audit ledger;
7. verify lifecycle remains disabled;
8. only then promote the Gateway image through the normal controlled deployment path.
