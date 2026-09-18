import { memo, useEffect, useRef, useState } from "react";
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import Markdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import {
  askProject,
  createProject,
  createMessage,
  deleteProject,
  fetchLoadedModels,
  fetchManagerState,
  fetchProjects,
  importProjectZip,
  indexProject,
  loadSettings,
  saveSettings,
  sendChat,
  switchModel,
  updateProject,
} from "./lib";
import type {
  ChatMessage,
  ChatSettings,
  ModelProfile,
  ProjectSummary,
} from "./types";

const WELCOME_MESSAGES = [
  "Готов, когда ты готов.",
  "Чем сегодня займемся?",
  "С чего начнем?",
  "Что разбираем?",
  "Закидывай задачу.",
];

function CodeBlock({
  className,
  children,
  ...rest
}: ComponentPropsWithoutRef<"code">) {
  const rawCode = extractText(children).replace(/\n$/, "");
  const language =
    className
      ?.split(/\s+/)
      .find((token) => token.startsWith("language-"))
      ?.replace(/^language-/, "") ?? "";
  const [copied, setCopied] = useState(false);

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(rawCode);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="code-block">
      <button
        type="button"
        className="code-copy-badge"
        onClick={onCopy}
        aria-label={copied ? "Скопировано" : "Копировать код"}
        title={copied ? "Скопировано" : "Копировать код"}
      >
        {language ? (
          <span className="code-block-language">{language}</span>
        ) : (
          <span className="code-block-language">code</span>
        )}
        <svg
          className="code-copy-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <rect x="9" y="9" width="10" height="10" rx="2" />
          <path d="M5 15V7a2 2 0 0 1 2-2h8" />
        </svg>
      </button>
      <div className="code-block-scroll">
        <pre>
          <code className={className} {...rest}>
            {children}
          </code>
        </pre>
      </div>
    </div>
  );
}

function extractText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map(extractText).join("");
  }
  if (node && typeof node === "object" && "props" in node) {
    const props = (node as { props?: { children?: ReactNode } }).props;
    return extractText(props?.children ?? "");
  }
  return "";
}

const MessageMarkdown = memo(function MessageMarkdown({
  content,
}: {
  content: string;
}) {
  return (
    <div className="message-markdown">
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          code({ className, children, ...props }) {
            const isInline = !className;
            if (isInline) {
              return (
                <code className={className} {...props}>
                  {children}
                </code>
              );
            }
            return (
              <CodeBlock className={className} {...props}>
                {children}
              </CodeBlock>
            );
          },
        }}
      >
        {content}
      </Markdown>
    </div>
  );
});

function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    createMessage(
      "assistant",
      WELCOME_MESSAGES[Math.floor(Math.random() * WELCOME_MESSAGES.length)],
    ),
  ]);
  const [draft, setDraft] = useState("");
  const [settings, setSettings] = useState<ChatSettings>(loadSettings);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeProfileId, setActiveProfileId] = useState<string>("");
  const [isSwitchingModel, setIsSwitchingModel] = useState(false);
  const [isIndexingProject, setIsIndexingProject] = useState(false);
  const [isSavingProject, setIsSavingProject] = useState(false);
  const [isDeletingProject, setIsDeletingProject] = useState(false);
  const [isImportingProject, setIsImportingProject] = useState(false);
  const [serviceState, setServiceState] = useState<string>("unknown");
  const [loadedModelIds, setLoadedModelIds] = useState<string[]>([]);
  const [projectForm, setProjectForm] = useState({
    id: "",
    label: "",
    path: "",
  });
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [replaceExisting, setReplaceExisting] = useState(true);
  const [purgeProjectFiles, setPurgeProjectFiles] = useState(false);
  const viewportRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    saveSettings(settings);
  }, [settings]);

  useEffect(() => {
    viewportRef.current?.scrollTo({
      top: viewportRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  useEffect(() => {
    let cancelled = false;

    async function syncState() {
      try {
        const [managerState, projectList] = await Promise.all([
          fetchManagerState(),
          fetchProjects().catch(() => []),
        ]);
        let nextLoadedModels: string[] = [];

        try {
          nextLoadedModels = await fetchLoadedModels();
        } catch {
          nextLoadedModels = [];
        }

        if (cancelled || managerState.profiles.length === 0) return;

        setProfiles(managerState.profiles);
        setProjects(projectList);
        setActiveProfileId(managerState.active ?? managerState.profiles[0].id);
        setLoadedModelIds(nextLoadedModels);
        setSettings((current) => {
          const activeProfile =
            managerState.profiles.find(
              (item) => item.id === managerState.active,
            ) ?? managerState.profiles[0];
          const nextProjectId =
            current.projectId ||
            projectList.find((item) => item.indexed)?.id ||
            projectList[0]?.id ||
            "";
          return {
            ...current,
            model: activeProfile.model,
            projectId: nextProjectId,
          };
        });
        const activeProfile =
          managerState.profiles.find(
            (item) => item.id === managerState.active,
          ) ?? managerState.profiles[0];
        const isBackendHealthy =
          managerState.backend_ready &&
          nextLoadedModels.includes(activeProfile.model);
        const nextServiceState = isBackendHealthy
          ? "active"
          : managerState.downloading
            ? "downloading"
            : managerState.service === "active" ||
                managerState.service === "activating"
              ? "loading"
              : "offline";
        setServiceState(nextServiceState);
        if (!projectForm.id && projectList.length > 0) {
          const nextProjectId =
            settings.projectId ||
            projectList.find((item) => item.indexed)?.id ||
            projectList[0]?.id ||
            "";
          const selectedProject =
            projectList.find((item) => item.id === nextProjectId) ??
            projectList[0];
          setProjectForm({
            id: selectedProject.id,
            label: selectedProject.label,
            path: selectedProject.path,
          });
        }
      } catch {
        if (cancelled) return;
        setProfiles([]);
        setProjects([]);
        setLoadedModelIds([]);
        setServiceState("offline");
      }
    }

    void syncState();
    const timer = window.setInterval(() => {
      void syncState();
    }, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [projectForm.id, settings.projectId]);

  async function onSubmit() {
    const content = draft.trim();
    if (!content || isSending) return;
    if (settings.mode === "project" && !settings.projectId) {
      setError("Сначала выбери проект для RAG.");
      return;
    }

    const nextUserMessage = createMessage("user", content);
    const nextMessages = [...messages, nextUserMessage];
    setMessages(nextMessages);
    setDraft("");
    setError("");
    setIsSending(true);

    try {
      if (settings.mode === "project") {
        const reply = await askProject(content, settings);
        setMessages((current) => [
          ...current,
          createMessage("assistant", reply.answer, reply.sources),
        ]);
      } else {
        const reply = await sendChat(nextMessages, settings);
        setMessages((current) => [
          ...current,
          createMessage("assistant", reply),
        ]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown request error");
    } finally {
      setIsSending(false);
    }
  }

  async function onModelChange(profileId: string) {
    if (!profileId || profileId === activeProfileId || isSwitchingModel) return;

    setError("");
    setIsSwitchingModel(true);

    try {
      await switchModel(profileId);
      setActiveProfileId(profileId);
      setServiceState("offline");
      setLoadedModelIds([]);
      const targetProfile = profiles.find((item) => item.id === profileId);
      if (targetProfile) {
        setSettings((current) => ({
          ...current,
          model: targetProfile.model,
        }));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Model switch failed");
    } finally {
      setIsSwitchingModel(false);
    }
  }

  async function onIndexProject() {
    if (!settings.projectId || isIndexingProject) return;

    setError("");
    setIsIndexingProject(true);

    try {
      await indexProject(settings.projectId);
      const nextProjects = await fetchProjects();
      setProjects(nextProjects);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Project indexing failed");
    } finally {
      setIsIndexingProject(false);
    }
  }

  async function onCreateProject() {
    if (!projectForm.id.trim() || !projectForm.path.trim()) {
      setError("Нужны id и path для проекта.");
      return;
    }

    setError("");
    setIsSavingProject(true);
    try {
      const nextProjects = await createProject(projectForm);
      setProjects(nextProjects);
      setSettings((current) => ({
        ...current,
        projectId: projectForm.id,
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Project creation failed");
    } finally {
      setIsSavingProject(false);
    }
  }

  async function onUpdateProject() {
    if (!projectForm.id.trim() || !projectForm.path.trim()) {
      setError("Нужны id и path для проекта.");
      return;
    }

    setError("");
    setIsSavingProject(true);
    try {
      const nextProjects = await updateProject(projectForm);
      setProjects(nextProjects);
      setSettings((current) => ({
        ...current,
        projectId: projectForm.id,
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Project update failed");
    } finally {
      setIsSavingProject(false);
    }
  }

  async function onDeleteProject() {
    if (!projectForm.id.trim()) {
      setError("Нужен id проекта.");
      return;
    }

    setError("");
    setIsDeletingProject(true);
    try {
      const deletedId = projectForm.id;
      const nextProjects = await deleteProject(deletedId, purgeProjectFiles);
      setProjects(nextProjects);
      const fallbackProject = nextProjects[0];
      setSettings((current) => ({
        ...current,
        projectId: fallbackProject?.id ?? "",
      }));
      setProjectForm({
        id: fallbackProject?.id ?? "",
        label: fallbackProject?.label ?? "",
        path: fallbackProject?.path ?? "",
      });
      setPurgeProjectFiles(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Project delete failed");
    } finally {
      setIsDeletingProject(false);
    }
  }

  async function onImportZip() {
    if (!projectForm.id.trim()) {
      setError("Нужен id проекта.");
      return;
    }
    if (!zipFile) {
      setError("Выбери zip-архив с исходниками.");
      return;
    }

    setError("");
    setIsImportingProject(true);
    try {
      const nextProjects = await importProjectZip({
        id: projectForm.id,
        label: projectForm.label || projectForm.id,
        file: zipFile,
        replaceExisting,
      });
      setProjects(nextProjects);
      setSettings((current) => ({
        ...current,
        projectId: projectForm.id,
      }));
      const selectedProject =
        nextProjects.find((item) => item.id === projectForm.id) ?? null;
      setProjectForm({
        id: selectedProject?.id ?? projectForm.id,
        label: (selectedProject?.label ?? projectForm.label) || projectForm.id,
        path: selectedProject?.path ?? `/srv/projects/${projectForm.id}`,
      });
      setZipFile(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ZIP import failed");
    } finally {
      setIsImportingProject(false);
    }
  }

  const activeProfile =
    profiles.find((profile) => profile.id === activeProfileId) ?? null;
  const activeProject =
    projects.find((project) => project.id === settings.projectId) ?? null;
  const isModelReady =
    activeProfile !== null && loadedModelIds.includes(activeProfile.model);
  const statusClass =
    serviceState === "active" && isModelReady
      ? "status-ok"
      : serviceState === "downloading"
        ? "status-downloading"
        : serviceState === "loading"
          ? "status-loading"
          : "status-error";
  const statusLabel =
    serviceState === "active" && isModelReady
      ? "Модель готова"
      : serviceState === "downloading"
        ? "Идёт загрузка модели по сети"
        : serviceState === "loading"
          ? "Модель загружается локально"
          : "Модель недоступна";

  return (
    <main className="shell">
      <section className="hero">
        <div>
          <p className="eyebrow">Archsrv Chat</p>
          <p className="lede">
            Чат с локальной моделью и режимом <code>project QA</code> через
            кодовый RAG.
          </p>
        </div>
        <div className="hero-actions">
          <div className="hero-badge">
            <span
              className={`status-dot ${statusClass}`}
              title={statusLabel}
              aria-label={statusLabel}
            />
            <div className="hero-badge-copy">
              <strong>{activeProfile?.label ?? "Профиль не выбран"}</strong>
              <span>
                {settings.mode === "project" && activeProject
                  ? `RAG: ${activeProject.label}`
                  : "Режим: обычный чат"}
              </span>
            </div>
          </div>
          <button
            className="settings-toggle"
            type="button"
            aria-label="Открыть настройки"
            onClick={() => setSettingsOpen((current) => !current)}
          >
            ⚙
          </button>
        </div>
      </section>

      <section className="workspace">
        <section className="panel chat-panel">
          <div className="panel-header">
            <h2>{settings.mode === "project" ? "Проект" : "Чат"}</h2>
            {settings.mode === "project" && activeProject ? (
              <p>
                Работа по коду проекта <code>{activeProject.label}</code>.
              </p>
            ) : null}
          </div>

          <div className="messages" ref={viewportRef}>
            {messages.map((message) => (
              <article key={message.id} className={`message ${message.role}`}>
                <div className="message-role">{message.role}</div>
                <div className="message-body">
                  <MessageMarkdown content={message.content} />
                </div>
                {message.sources?.length ? (
                  <div className="message-sources">
                    <div className="message-sources-title">Источники</div>
                    <ul className="source-list">
                      {message.sources.map((source) => (
                        <li
                          key={`${source.path}:${source.start_line}:${source.end_line}`}
                        >
                          <code>
                            {source.path}:{source.start_line}-{source.end_line}
                          </code>
                          {source.symbol ? <span>{source.symbol}</span> : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </article>
            ))}
            {isSending ? (
              <article className="message assistant pending">
                <div className="message-role">assistant</div>
                <div className="message-body">
                  {settings.mode === "project"
                    ? "Ищу контекст по проекту..."
                    : "Думаю..."}
                </div>
              </article>
            ) : null}
          </div>

          <div className="composer">
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                  event.preventDefault();
                  void onSubmit();
                }
              }}
              placeholder={
                settings.mode === "project"
                  ? "Например: где и как работает авторизация?"
                  : "Попроси код, архитектуру, shell-команды, отладку..."
              }
              rows={5}
            />
            <div className="composer-footer">
              <div className="composer-hint">
                <span>Ctrl/Cmd + Enter для отправки</span>
                {error ? <strong>{error}</strong> : null}
              </div>
              <button
                className="send-button"
                type="button"
                onClick={() => void onSubmit()}
              >
                {isSending ? "Отправка..." : "Отправить"}
              </button>
            </div>
          </div>
        </section>
      </section>

      {settingsOpen ? (
        <div
          className="settings-backdrop"
          onClick={() => setSettingsOpen(false)}
        >
          <aside
            className="panel settings-drawer"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="panel-header settings-drawer-header">
              <div>
                <h2>Сессия</h2>
                <p>Модель, режим запроса и проектный RAG.</p>
              </div>
              <button
                className="settings-close"
                type="button"
                aria-label="Закрыть настройки"
                onClick={() => setSettingsOpen(false)}
              >
                ×
              </button>
            </div>

            <label className="field">
              <span>Режим</span>
              <select
                value={settings.mode}
                onChange={(event) =>
                  setSettings((current) => ({
                    ...current,
                    mode: event.target.value as ChatSettings["mode"],
                  }))
                }
              >
                <option value="chat">Обычный чат</option>
                <option value="project">Вопрос по проекту</option>
              </select>
            </label>

            <label className="field">
              <span>Модель</span>
              <select
                value={activeProfileId}
                onChange={(event) => void onModelChange(event.target.value)}
                disabled={isSwitchingModel}
              >
                {profiles.length === 0 ? (
                  <option value="">
                    {isSwitchingModel
                      ? "Переключение..."
                      : "Нет данных от manager"}
                  </option>
                ) : null}
                {profiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {profile.label}
                  </option>
                ))}
              </select>
              <small className="field-meta">
                {isSwitchingModel
                  ? "Переключение профиля..."
                  : activeProfile
                    ? `Сейчас загружена: ${activeProfile.label}`
                    : "Нет активного профиля"}
              </small>
            </label>

            <label className="field">
              <span>Проект</span>
              <select
                value={settings.projectId}
                onChange={(event) => {
                  const nextProjectId = event.target.value;
                  const selectedProject =
                    projects.find((item) => item.id === nextProjectId) ?? null;
                  setSettings((current) => ({
                    ...current,
                    projectId: nextProjectId,
                  }));
                  setProjectForm({
                    id: selectedProject?.id ?? nextProjectId,
                    label: selectedProject?.label ?? "",
                    path: selectedProject?.path ?? "",
                  });
                }}
                disabled={projects.length === 0}
              >
                {projects.length === 0 ? (
                  <option value="">RAG API пока не вернула проекты</option>
                ) : null}
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.label}
                    {project.indexed ? "" : " (не проиндексирован)"}
                  </option>
                ))}
              </select>
              <small className="field-meta">
                {activeProject
                  ? activeProject.indexed
                    ? `Индекс готов: ${activeProject.chunk_count} чанков`
                    : "Индекс ещё не построен"
                  : "Сначала выбери проект"}
              </small>
            </label>

            <div className="field-actions">
              <button
                className="ghost-button"
                type="button"
                onClick={() => void onIndexProject()}
                disabled={!settings.projectId || isIndexingProject}
              >
                {isIndexingProject ? "Индексирую..." : "Переиндексировать"}
              </button>
            </div>

            <div className="project-editor">
              <div className="field">
                <span>ID проекта</span>
                <input
                  type="text"
                  value={projectForm.id}
                  onChange={(event) =>
                    setProjectForm((current) => ({
                      ...current,
                      id: event.target.value,
                    }))
                  }
                  placeholder="proj1"
                />
              </div>

              <div className="field">
                <span>Название</span>
                <input
                  type="text"
                  value={projectForm.label}
                  onChange={(event) =>
                    setProjectForm((current) => ({
                      ...current,
                      label: event.target.value,
                    }))
                  }
                  placeholder="proj1"
                />
              </div>

              <div className="field">
                <span>Путь на сервере</span>
                <input
                  type="text"
                  value={projectForm.path}
                  onChange={(event) =>
                    setProjectForm((current) => ({
                      ...current,
                      path: event.target.value,
                    }))
                  }
                  placeholder="/srv/projects/proj1"
                />
              </div>

              <div className="field">
                <span>ZIP с проектом</span>
                <input
                  type="file"
                  accept=".zip,application/zip"
                  onChange={(event) =>
                    setZipFile(event.target.files?.[0] ?? null)
                  }
                />
                <small className="field-meta">
                  {zipFile
                    ? `Выбран файл: ${zipFile.name}`
                    : "Можно загрузить архив ветки напрямую из браузера"}
                </small>
              </div>

              <label className="field checkbox-field">
                <span>Поверх существующего проекта</span>
                <input
                  type="checkbox"
                  checked={replaceExisting}
                  onChange={(event) => setReplaceExisting(event.target.checked)}
                />
              </label>

              <label className="field checkbox-field">
                <span>Удалить файлы и индексы</span>
                <input
                  type="checkbox"
                  checked={purgeProjectFiles}
                  onChange={(event) =>
                    setPurgeProjectFiles(event.target.checked)
                  }
                />
              </label>

              <div className="field-actions field-actions-row">
                <button
                  className="ghost-button"
                  type="button"
                  onClick={() => void onCreateProject()}
                  disabled={isSavingProject}
                >
                  {isSavingProject ? "Сохраняю..." : "Добавить"}
                </button>
                <button
                  className="ghost-button"
                  type="button"
                  onClick={() => void onUpdateProject()}
                  disabled={isSavingProject}
                >
                  {isSavingProject ? "Сохраняю..." : "Сохранить"}
                </button>
                <button
                  className="ghost-button danger-button"
                  type="button"
                  onClick={() => void onDeleteProject()}
                  disabled={isDeletingProject}
                >
                  {isDeletingProject ? "Удаляю..." : "Удалить"}
                </button>
                <button
                  className="ghost-button"
                  type="button"
                  onClick={() => void onImportZip()}
                  disabled={isImportingProject}
                >
                  {isImportingProject ? "Импорт..." : "Импорт ZIP"}
                </button>
              </div>
            </div>

            <label className="field">
              <span>Системный промпт</span>
              <textarea
                value={settings.systemPrompt}
                onChange={(event) =>
                  setSettings((current) => ({
                    ...current,
                    systemPrompt: event.target.value,
                  }))
                }
                rows={8}
              />
            </label>

            <div className="grid-two">
              <label className="field">
                <span>Температура</span>
                <input
                  type="number"
                  min="0"
                  max="2"
                  step="0.1"
                  value={settings.temperature}
                  onChange={(event) =>
                    setSettings((current) => ({
                      ...current,
                      temperature: Number(event.target.value),
                    }))
                  }
                />
              </label>

              <label className="field">
                <span>Макс. токены</span>
                <input
                  type="number"
                  min="64"
                  max="6000"
                  step="64"
                  value={settings.maxTokens}
                  onChange={(event) =>
                    setSettings((current) => ({
                      ...current,
                      maxTokens: Number(event.target.value),
                    }))
                  }
                />
              </label>
            </div>

            <button
              className="ghost-button"
              type="button"
              onClick={() => {
                setMessages([
                  createMessage(
                    "assistant",
                    "Новая сессия. Можно просить код, команды или помощь с ревью.",
                  ),
                ]);
                setError("");
                setSettingsOpen(false);
              }}
            >
              Очистить чат
            </button>
          </aside>
        </div>
      ) : null}
    </main>
  );
}

export default App;
