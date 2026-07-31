# Documentation

## Stage 01

Goal: read-only audit and classification of `magerya_api` stage database.

See [AGENTS.md](../AGENTS.md), [current-stage.md](current-stage.md), and
[stage-01-acceptance.md](stage-01-acceptance.md).

### Local dumps (not in git)

| Path | Role |
|------|------|
| `dumps/stage_magerya_api.dump` | Primary restore target for `./restore.sh` |
| `kgz-20231204.dump` | Additional local dump at repository root |

These files are preserved locally and listed in `.gitignore`.
