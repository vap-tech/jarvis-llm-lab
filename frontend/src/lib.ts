import type {
  ChatMessage,
  ChatSettings,
  ModelProfile,
  ProjectSummary,
  SourceRef,
} from "./types";

export const STORAGE_KEY = "archsrv-chat-settings";

export const defaultSettings: ChatSettings = {
  model: "Qwen/Qwen2.5-Coder-14B-Instruct-GGUF",
  systemPrompt:
    "You are a concise senior software engineer. Produce direct, practical answers and code.",
  temperature: 0.2,
  maxTokens: 6000,
  mode: "chat",
  projectId: "",
};

export function loadSettings(): ChatSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultSettings;
    return {
      ...defaultSettings,
      ...(JSON.parse(raw) as Partial<ChatSettings>),
    };
  } catch {
    return defaultSettings;
  }
}

export function saveSettings(settings: ChatSettings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

export async function fetchManagerState(): Promise<{
  active: string | null;
  profiles: ModelProfile[];
  service: string;
  backend_ready: boolean;
  downloading: boolean;
}> {
  const response = await fetch("/manager/profiles");

  if (!response.ok) {
    throw new Error(`Failed to load profiles: ${response.status}`);
  }

  return (await response.json()) as {
    active: string | null;
    profiles: ModelProfile[];
    service: string;
    backend_ready: boolean;
    downloading: boolean;
  };
}

export async function fetchLoadedModels(): Promise<string[]> {
  const response = await fetch("/api/v1/models");

  if (!response.ok) {
    throw new Error(`Failed to load models: ${response.status}`);
  }

  const data = (await response.json()) as {
    data?: Array<{ id?: string }>;
    models?: Array<{ id?: string; model?: string; name?: string }>;
  };

  const loaded =
    data.data?.map((item) => item.id).filter(Boolean) ??
    data.models
      ?.map((item) => item.id ?? item.model ?? item.name)
      .filter(Boolean) ??
    [];

  return loaded as string[];
}

export async function switchModel(profileId: string): Promise<void> {
  const response = await fetch("/manager/select", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ id: profileId }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Failed to switch model: ${response.status}`);
  }
}

export async function fetchProjects(): Promise<ProjectSummary[]> {
  const response = await fetch("/rag/projects");

  if (!response.ok) {
    throw new Error(`Failed to load projects: ${response.status}`);
  }

  const data = (await response.json()) as {
    projects?: ProjectSummary[];
  };

  return data.projects ?? [];
}

export async function indexProject(projectId: string): Promise<void> {
  const response = await fetch("/rag/index", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ project: projectId }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Failed to index project: ${response.status}`);
  }
}

export async function createProject(payload: {
  id: string;
  label: string;
  path: string;
}): Promise<ProjectSummary[]> {
  const response = await fetch("/rag/projects/create", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Failed to create project: ${response.status}`);
  }

  const data = (await response.json()) as { projects?: ProjectSummary[] };
  return data.projects ?? [];
}

export async function updateProject(payload: {
  id: string;
  label: string;
  path: string;
}): Promise<ProjectSummary[]> {
  const response = await fetch("/rag/projects/update", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Failed to update project: ${response.status}`);
  }

  const data = (await response.json()) as { projects?: ProjectSummary[] };
  return data.projects ?? [];
}

export async function deleteProject(
  projectId: string,
  purgeFiles = false,
): Promise<ProjectSummary[]> {
  const response = await fetch("/rag/projects/delete", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ id: projectId, purge_files: purgeFiles }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Failed to delete project: ${response.status}`);
  }

  const data = (await response.json()) as { projects?: ProjectSummary[] };
  return data.projects ?? [];
}

export async function importProjectZip(payload: {
  id: string;
  label: string;
  file: File;
  replaceExisting: boolean;
}): Promise<ProjectSummary[]> {
  const form = new FormData();
  form.set("id", payload.id);
  form.set("label", payload.label);
  form.set("replace_existing", String(payload.replaceExisting));
  form.set("file", payload.file);

  const response = await fetch("/rag/projects/import-zip", {
    method: "POST",
    body: form,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Failed to import zip: ${response.status}`);
  }

  const data = (await response.json()) as { projects?: ProjectSummary[] };
  return data.projects ?? [];
}

export async function sendChat(
  messages: ChatMessage[],
  settings: ChatSettings,
): Promise<string> {
  const response = await fetch("/api/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: settings.model,
      stream: false,
      temperature: settings.temperature,
      max_tokens: settings.maxTokens,
      messages: [
        ...(settings.systemPrompt.trim()
          ? [{ role: "system", content: settings.systemPrompt }]
          : []),
        ...messages.map(({ role, content }) => ({ role, content })),
      ],
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with ${response.status}`);
  }

  const data = (await response.json()) as {
    choices?: Array<{
      message?: {
        content?: string;
      };
    }>;
  };

  return data.choices?.[0]?.message?.content?.trim() || "Empty response";
}

export async function askProject(
  question: string,
  settings: ChatSettings,
): Promise<{ answer: string; sources: SourceRef[] }> {
  const response = await fetch("/rag/ask", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      project: settings.projectId,
      question,
      model: settings.model,
      max_tokens: settings.maxTokens,
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Project request failed with ${response.status}`);
  }

  const data = (await response.json()) as {
    answer?: string;
    sources?: SourceRef[];
  };

  return {
    answer: data.answer?.trim() || "Empty response",
    sources: data.sources ?? [],
  };
}

export function createMessage(
  role: ChatMessage["role"],
  content: string,
  sources?: SourceRef[],
): ChatMessage {
  const id =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;

  return {
    id: `${role}-${id}`,
    role,
    content,
    sources,
  };
}
