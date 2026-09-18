# Состояние исходного сервера

Снимок проверен 18 сентября 2026 года перед архивированием.

## Платформа

- Arch Linux, kernel `6.19.10-arch1-1`, x86-64.
- 2 × Intel Xeon E5-2637 v4, суммарно 8 физических ядер / 16 потоков.
- 62 GiB RAM и 31 GiB swap.
- AMD Radeon VII (Vega 20), драйвер RADV/Vulkan.
- Корневой Btrfs 238 GiB: 77 GiB занято, 160 GiB свободно.

Значимые версии пакетов: CMake 4.3.1, GCC 15.2.1, Git 2.53.0, nginx 1.28.3, Python 3.14.3, Mesa 26.0.3, Vulkan headers/loader/tools 1.4.341 и `vulkan-radeon` 26.0.3.

Python-зависимости, непосредственно необходимые сохранённому RAG-коду, закреплены в `rag-api/requirements.txt`: NumPy 2.3.3, SciPy 1.17.1, scikit-learn 1.8.0 и tree-sitter-language-pack 0.10.0. Исходное virtualenv также содержало ML-пакеты Torch, Transformers, sentence-transformers, FAISS и CUDA-библиотеки, но сохранённый код их не импортирует; установщик их не восстанавливает.

## Рабочее состояние

- `llama-server.service`, `llama-manager.service`, `archsrv-rag.service` и `nginx.service` были active.
- Активная модель: `Qwen/Qwen2.5-Coder-7B-Instruct-GGUF`, файл `qwen2.5-coder-7b-instruct-q4_k_m.gguf`.
- Контекст: 16 384 на каждый из четырёх слотов; `GPU_LAYERS=99`.
- Наблюдаемая генерация: примерно 62–67 токенов/с.
- `/health` модели и RAG API отвечали успешно; менеджер сообщал `backend_ready: true`.
- В журналах не было ошибок служб. nginx выдавал только предупреждение о `types_hash`.

## Исключённые объёмы

- Hugging Face cache: 67 GiB.
- Рабочая копия и build `llama.cpp`: 1.2 GiB; вместо неё сохранены upstream URL, точный commit и параметры сборки.
- Python virtualenv: 5.3 GiB; он восстанавливается из requirements.
- RAG-индексы: 86 MiB; это производные данные.
- Индексируемые проекты: 42 MiB; пользователь явно исключил их из архива.

На момент снимка в RAG было семь записей и около 28 946 фрагментов. Исторические пути и параметры сохранены в `system/etc/archsrv-rag/projects.json`, но при чистой установке используется `deploy/projects.empty.json`.

