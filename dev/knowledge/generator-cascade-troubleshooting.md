# Diagnosing a truncated fabric → pod → rack cascade

The cascade fails silently. A pod that never generates leaves no error anywhere: no failed flow, no
exception, just missing devices. This is how to tell the causes apart, ordered by how often they are
the real answer.

## 1. Rule out configuration first — these are not platform faults

All three are properties of this repository, and all three present as "the generators don't trigger".

| Cause | Symptom | Check |
| --- | --- | --- |
| `triggers.yml` never loaded — neither `inv load` nor repository sync does it (AGENTS.md) | Fabric tier builds, nothing after it | Any `CoreNodeTriggerRule` for `NetworkPod` / `LocationRack`? |
| Running on the default branch — every rule is `branch_scope: other_branches`, which compiles to `infrahub.branch.name != main` | Super-spines appear on `main`, no spines ever | Is the work on a non-default branch? |
| No automatic entry point — all four dispatch paths for `generate-fabric` are closed (`execute_in_proposed_change: false`, `execute_after_merge: false`, no `CoreGroupTriggerRule`, no `NetworkFabric` node rule) | Creating or resizing a fabric starts nothing at all | Was the fabric generator invoked explicitly? |

`tests/integration/test_generator_chain.py` encodes all three as assertions, and
`tests/integration/cascade.py::provision_fabric_cascade` performs the setup correctly — use it rather
than re-deriving it.

## 2. Rule out the host

Cheap to check and, in this repo's experience, a more likely explanation than a platform bug.

The integration stacks put the repository they serve under pytest's temp root, which on many hosts is a
**tmpfs** — RAM, not disk. Fill it and the symptoms are wildly misleading: unrelated fixtures error,
the Infrahub server becomes unreachable mid-run (`ServerNotReachableError`), tiers time out, and the
host may start failing to fork. See `dev/guides/compare-infrahub-versions.md` for the
`PYTEST_DEBUG_TEMPROOT` setting that avoids it.

So before concluding anything about Infrahub: check free space **and** memory, confirm `/tmp` is not
tmpfs-backed and near-full, and confirm the stack's containers stayed healthy for the whole run.

## 3. Then look at dispatch

If configuration and host are clean, the question is whether each eligible pod actually got a generator
run. The authoritative check is the generator-instance list on the branch, not the logs:

```graphql
query { CoreGeneratorInstance { count edges { node { display_label status { value } } } } }
```

Expect one `generate-pod` instance per non-fabric pod, and one `generate-rack` per rack. A pod whose
checksum is set but which has **no** instance was never dispatched.

Pair it with the per-pod state:

| Pod    | role   | checksum | spines wanted | spines built |
| ------ | ------ | -------- | ------------- | ------------ |
| Pod-A1 | fabric | SET      | 4             | 0 — correct, `PodGenerator` skips fabric pods |
| Pod-A2 | cpu    | SET      | 4             | 0 — suspect |
| Pod-A3 | cpu    | SET      | 4             | 4 — fine |

A stamped pod with no spines means the stamp landed but no generator ran. An unstamped pod means the
fabric generator never reached `update_checksum` (`generate_fabric.py`), so look upstream instead.

## Why a truncated cascade never repairs itself

`generate_fabric.py` writes a pod's checksum only when the computed value differs. Once a pod is
stamped, re-running the fabric generator writes nothing, emits no `NodeUpdatedEvent`, and therefore
cannot re-dispatch the pod generator. Whatever the reason a dispatch was missed, the tier stays broken
until someone clears the checksum by hand.

Idempotence is the intent of that guard, and `test_rerunning_upstream_does_not_restamp` asserts it
deliberately. The consequence worth knowing is the other half: it converts any one-off missed dispatch
into a permanent gap. A fix would need an explicit re-dispatch path, or a generator-instance success
check, rather than relying on a value change.

## Appendix: one unexplained observation, not a confirmed defect

On 1.10.6 a run was seen in exactly the "Pod-A2" state above: both pod checksums set, a `generate-pod`
instance for Pod-A3 and its racks but **none for Pod-A2**, one
`Beginning subflow run 'Run generator generate-pod'` in the worker logs instead of two, no error
anywhere, and no recovery after 15 minutes.

That observation is recorded because the diagnostic pattern is useful — but it must **not** be cited as
a known Infrahub bug. It was collected on a host whose tmpfs temp root had been filled to 13 GB by a
harness bug (virtualenvs being copied into it), i.e. under memory pressure severe enough that the same
host was intermittently unable to fork. Losing queued work under those conditions needs no platform
explanation. The frequency was never established, and whether 1.11.x behaves differently was never
tested.

If it recurs on a host verified healthy by section 2, then it is worth reporting upstream — with the
generator-instance evidence above, which is what makes the case.

Also seen once on 1.10.6, unrelated to the above and on a group-membership event rather than a node
update:

```text
Error emitting event: infrahub.group.member_added
pydantic_core._pydantic_core.ValidationError: 1 validation error for Event
```
