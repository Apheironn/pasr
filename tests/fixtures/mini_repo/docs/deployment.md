# Deployment

## Rollout

We ship with a blue green cutover behind a weighted load balancer so a bad
release can be drained without downtime.

Database schema migrations run in an expand and contract sequence: additive
columns first, backfill, then the destructive drop in a later release.

## Secrets

Application credentials are pulled from the vault sidecar at boot and never
written to the container image or to disk.

## Observability

Every service exports a golden signals dashboard covering latency, traffic,
errors and saturation, wired to the on call paging policy.

## Capacity

Autoscaling targets sixty percent CPU with a five minute stabilization window
to avoid thrashing during short traffic spikes.
