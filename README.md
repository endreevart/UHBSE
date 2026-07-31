# Human simulator — stage DB

Локальная копия stage-базы `magerya_api` с dev-сервера. Agent-first репозиторий для read-only профилирования (stage-01).

Полный гайд для агента: [AGENTS.md](AGENTS.md)

## Структура

```
├── AGENTS.md              # манифест агента
├── .cursor/               # rules, skills, commands
├── config/                # policy и шаблон sources
├── src/human_simulator/   # Python tooling
├── tests/
├── artifacts/stage-01/    # deliverables этапа
├── private/               # локальные секреты (не в git)
├── dumps/                 # дампы БД (не в git, не удалять)
├── docker-compose.yml
├── restore.sh
└── db.env.example           # шаблон (скопировать в db.env)
```

## Подключение

| Параметр | Значение |
|----------|----------|
| Host | `localhost` |
| Port | `5434` |
| Database | `magerya_api` |
| User | `magerya_api` |
| Password | `db.env` → `POSTGRES_PASSWORD` (не в git) |

```bash
cp db.env.example db.env   # первый запуск: задайте POSTGRES_PASSWORD
psql -h localhost -p 5434 -U magerya_api -d magerya_api
```

## Команды

```bash
# БД
docker compose up -d
./restore.sh                    # dumps/stage_magerya_api.dump

# Python
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
audit --root . verify-stage
```

## Cursor

- `/stage-01-start` — начать pipeline stage-01
- `/stage-01-check` — проверить готовность этапа

## Локальные дампы

Не коммитятся, не удалять:

- `dumps/stage_magerya_api.dump`
- `kgz-20231204.dump`
