# Архитектура стенда

Снимок сделан с `kot@192.168.1.204` 18 сентября 2026 года. Сервер работал на Arch Linux, двух Intel Xeon E5-2637 v4, 62 GiB RAM и Radeon VII. Модели исполнялись через Vulkan.

## Поток запроса

```text
браузер :80 (nginx)
  ├─ /api/*     -> llama.cpp :8080
  ├─ /manager/* -> менеджер моделей :8081
  └─ /rag/*     -> RAG API :8082 -> llama.cpp :8080
```

`llama-server.service` запускает OpenAI-совместимый сервер из закреплённой сборки `llama.cpp`. Скрипт запуска читает `/etc/llama-server/current.env`; `--hf-repo` и `--hf-file` позволяют скачать отсутствующий GGUF с Hugging Face при первом старте.

`llama-manager.service` запускает небольшой HTTP-сервер от root. `GET /profiles` и `GET /state` возвращают профили и состояние. `POST /select` копирует выбранный `model-<id>.env` в `current.env` и перезапускает `llama-server.service`.

`archsrv-rag.service` индексирует каталоги с исходным кодом. Tree-sitter выделяет структуры языка; слишком большие или неподдерживаемые файлы режутся перекрывающимися окнами. Тексты, имена символов и пути индексируются `TfidfVectorizer` с униграммами и биграммами. При вопросе LLM сначала расширяет поисковый запрос, затем результаты TF-IDF объединяются с простым поиском по словам. Лучшие фрагменты передаются модели вместе с путями и номерами строк.

RAG API предоставляет:

- `GET /health` и `GET /projects`;
- `POST /index` и `POST /ask`;
- `POST /projects/create`, `/projects/update`, `/projects/delete`;
- `POST /projects/import-zip`.

Веб-интерфейс — React 19 + TypeScript + Vite. Он использует `react-markdown`, GFM, подсветку кода через highlight.js и обращается к OpenAI API, менеджеру моделей и RAG API через маршруты nginx. На сервере была только production-сборка; полный исходный frontend-проект позднее восстановлен из ноутбучного репозитория и находится в `frontend/`. Серверная сборка сохранена отдельно в `web-ui/`.

## Зафиксированная версия llama.cpp

- Репозиторий: `https://github.com/ggml-org/llama.cpp.git`
- Commit: `0fcb3760b2b9a3a496ef14621a7e4dad7a8df90f`
- Commit message: `fix: Use lower-case proxy headers naming (#21235)`
- Сборка: `Release`, `GGML_VULKAN=ON`, native CPU, OpenMP, web UI и OpenSSL.
- Рабочий бинарник: `/home/kot/llama.cpp/build/bin/llama-server`.

Текущий профиль сервера был `Qwen2.5-Coder-7B-Instruct Q4_K_M`, 16 384 токена контекста, все слои на GPU. Сохранены семь профилей; сами GGUF-файлы и Hugging Face cache не копировались.

## Данные и права

- `/etc/llama-server`: профили моделей и активный профиль.
- `/etc/archsrv-rag/projects.json`: реестр индексируемых проектов.
- `/opt/archsrv-rag/app`: RAG-код.
- `/opt/archsrv-rag/.venv`: создаваемое Python-окружение.
- `/srv/projects`: загруженные или размещённые исходные проекты.
- `/srv/rag`: производные индексы (`chunks.jsonl`, sparse matrix, metadata, vectorizer).
- `/var/www/archsrv`: статический интерфейс.

Службы модели и RAG работали от пользователя `kot`; менеджер — от root, поскольку он перезапускает systemd-службу. Конфигурация RAG должна принадлежать сервисному пользователю, так как API редактирует список проектов.

## Ограничения исходной реализации

Все API слушают `0.0.0.0`, CORS разрешён для любого origin, а nginx не выполняет аутентификацию. Менеджер на порту 8081 может перезапускать модель. Восстановленный стенд следует держать в доверенной сети либо закрыть порты 8080–8082 firewall и добавить аутентификацию перед публикацией.

`llama-model-select` — ранняя CLI-версия переключателя: она знает только три имени, причём профиль `model-14b.env` в финальной конфигурации отсутствует. Веб-интерфейс использует более новый `llama-manager.py`, который динамически читает все профили.
