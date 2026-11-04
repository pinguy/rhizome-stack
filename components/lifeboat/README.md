# Rhizome Lifeboat source companion

Lifeboat is an independent, deterministic checkpoint and recovery controller
for OpenClaw/Rhizome. It does not ask an LLM whether to restore. SQLite files
are captured through the online backup API, every artefact is hashed, recovery
attempts are bounded, damaged state is quarantined and retention is fail-closed.

This release contains the controller source and its regression tests. It does
**not** contain the reference machine's production configuration, checkpoint
store, recovery receipts, database schema hashes, service account, Monit rules
or root installation scripts. Those are host-specific security policy, not
portable defaults.

## Safe adoption

1. Copy `config.example.toml` outside the source tree.
2. Replace every example path, mount identity, service command and schema
   expectation with values inspected on the target host.
3. Keep `[retention].enabled = false` until checkpoint creation, verification,
   restore drill and protected-store dry run have all passed.
4. Test genuine corruption only in a disposable environment.
5. Review and install privileged service integration separately. Merely having
   this source in a Rhizome Stack release does not arm automatic recovery.

Run the unprivileged suite:

```bash
PYTHONPATH=components/lifeboat/src \
  python3 -m unittest discover -s components/lifeboat/tests -v
```

The packaged source corresponds to Lifeboat revision
`e995ffe0eb575f79031a81a048a38958f07a7689`. The independently tested recovery
baseline is `2c487b4dd7429893d7fe23f8c5e6b3d1e5c6b4fe`; later retained changes add
the 3 daily / 2 weekly / 1 monthly pruning policy and documentation. Production
deployment remains a separate, operator-reviewed operation.
