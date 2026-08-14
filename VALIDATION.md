# V1.0 validation record

Validation performed in the build environment before packaging:

- Python test suite: **30 passed**.
- `python -m compileall -q src`: passed.
- Docker Compose YAML parsed successfully.
- Every `.ts` / `.tsx` source file parsed successfully with the available TypeScript compiler API.
- Python wheel built successfully with the locally installed build tooling and its required package files were inspected.
- ZIP integrity is checked during final packaging.

Not executable in the build environment:

- Docker itself is not installed, so `docker compose up/build` could not be run here.
- The container environment cannot reach the npm registry, so a full `npm install`, ESLint run, and Next.js production build could not be executed here. The frontend package versions were selected against current official framework documentation and the source was syntax-validated, but the first environment with npm registry access should run `npm install && npm run lint && npm run build` (the included GitHub Actions workflow does this).
- No live GitHub App, Codex, or Claude credentials are available in the build environment, so a real Issue → Agent → PR → CI → Merge run could not be performed here.

These limitations are intentionally documented rather than represented as completed end-to-end validation.

- Secret smoke scan across packaged source (excluding intentional scanner fixtures): passed.
- Wheel import smoke test: passed.

## PostgreSQL 18 volume compatibility

- Compose mounts the named PostgreSQL volume at `/var/lib/postgresql`, which is the supported persistent-volume target for the official PostgreSQL 18+ image.
- Fresh-volume recovery command after upgrading from the broken V1.0 Compose definition: `docker compose down -v` followed by `docker compose up --build`. Only use `-v` when the existing database volume contains no data that must be retained.
