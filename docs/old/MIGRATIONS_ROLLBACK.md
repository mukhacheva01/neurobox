# Миграции БД — откат (rollback)

При добавлении новых миграций в `migrations/` рекомендуется предусматривать обратный шаг.

## Правило (S3 из BACKLOG)

У каждой новой миграции должен быть либо:
- обратный SQL (например `migrations/XXX_down.sql`), либо
- краткое описание в этом файле: как откатить изменения вручную.

## Пример обратного шага

Если миграция `023_new_feature.sql` создаёт таблицу `new_feature` и колонку `users.new_col`:

```sql
-- 023_new_feature_down.sql (откат)
ALTER TABLE users DROP COLUMN IF EXISTS new_col;
DROP TABLE IF EXISTS new_feature;
```

Запуск отката — вручную через `psql` или `docker compose exec postgres psql -U neurobox -d neurobox -f /path/to/023_new_feature_down.sql`.

## Текущие миграции

Обратные шаги для старых миграций не задокументированы. Для всех **новых** миграций (024 и далее) добавлять описание отката сюда или прикладывать `*_down.sql`.
