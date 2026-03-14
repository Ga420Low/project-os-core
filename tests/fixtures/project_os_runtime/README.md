This directory is a versioned replay fixture.

It is not the live Project OS runtime.

Purpose:

- keep a small sandboxed runtime snapshot for replay/debug scenarios
- preserve OpenClaw replay fixtures and a sample SQLite state
- avoid confusing fixture data with the real runtime under `D:\ProjectOS\runtime`

The config files in `config/` point back into this fixture tree on purpose.
