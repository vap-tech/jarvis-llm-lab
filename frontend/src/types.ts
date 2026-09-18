export type Role = "system" | "user" | "assistant";

export type ChatMessage = {
  id: string;
  role: Role;
  content: string;
  sources?: SourceRef[];
};

export type ChatSettings = {
  model: string;
  systemPrompt: string;
  temperature: number;
  maxTokens: number;
  mode: ChatMode;
  projectId: string;
};

export type ModelProfile = {
  id: string;
  label: string;
  model: string;
  file: string;
  context: number;
};

export type ChatMode = "chat" | "project";

export type ProjectSummary = {
  id: string;
  label: string;
  path: string;
  indexed: boolean;
  indexed_at?: string | null;
  chunk_count: number;
};

export type SourceRef = {
  path: string;
  start_line: number;
  end_line: number;
  symbol?: string;
};
