# Safe deployment checklist

1. Do **not** stop the existing monitors while preparing the repository.
2. Run syntax checks and unit tests in a separate checkout.
3. Before switching services, snapshot the live databases with SQLite backup API; verify integrity.
4. Confirm each template's `ExecStart` points to the correct directory and database path.
5. Disable/stop legacy services before enabling corresponding template instances.
6. Start the five instances one by one, checking `Found 20 recent videos to inspect` and `Cycle complete`.
7. Check for rate limits; back off if YouTube reports throttling.
8. Generate reports, verify all five channels appear once initial data exists, and verify nginx serves them.
9. Run a restore test from an off-device backup.
10. Only then consider removing obsolete unit files.
