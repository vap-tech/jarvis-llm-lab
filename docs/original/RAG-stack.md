# Code RAG Stack

## Goal

Use a local LLM on the server to answer questions about a real project repository, for example:

`Где и как у нас работает авторизация?`

The system should:

- search the project codebase for relevant implementation details
- send only the useful context to the model
- return an answer grounded in real files and code fragments

This is not model fine-tuning. This is retrieval plus prompting.

## Proposed Stack

### 1. Generation model

Existing local inference server:

- `llama.cpp`
- `llama-server`
- `OpenAI-compatible /v1/chat/completions`

Recommended usage:

- `DeepSeek Coder V2 Lite` or `Qwen coder` profile for code questions
- `Qwen2.5 14B Instruct Q5` for general chat

### 2. Parsing and chunking

Use:

- `tree-sitter`

Why:

- split code by real syntax units instead of raw text
- extract useful metadata:
  - file path
  - language
  - symbol type
  - symbol name
  - line range

Chunk examples:

- one function
- one class
- one method
- one route handler
- one middleware block
- one config section

Fallback for unsupported files:

- markdown, yaml, env, sql, json can be chunked by simpler text rules

### 3. Embedding model

Use a separate embedding model.

Purpose:

- convert code chunks and user questions into vectors
- search by meaning, not only by literal string match

Important:

- embedding model does not generate answers
- it is only used for search

Practical choices:

- start with a small local sentence-transformer style embedding model
- run it on CPU first
- move to GPU only if indexing speed becomes annoying

Recommendation:

- keep this part simple in v1
- do not mix it with the main chat model

### 4. Vector index

Use:

- `FAISS` for v1

Why:

- simple
- local
- fast enough
- no heavy server dependency

Store alongside vectors:

- chunk id
- file path
- symbol name
- line range
- raw chunk text
- language
- repo id

Possible later upgrade:

- `LanceDB` if you want a more database-like local experience

### 5. Retrieval service

Use:

- a small Python service

Purpose:

- accept a user question
- search the indexed project
- gather best matching code chunks
- build a grounded prompt
- call `llama-server`
- return answer plus source references

This is orchestration glue, not another AI model.

### 6. Web UI integration

Current web UI can stay.

Extend it with:

- project selector
- optional mode selector:
  - `chat`
  - `code`
  - `project QA`
- answer source list
- optional “show retrieved context” panel

## End-to-End Flow

Example input:

`Где и как у нас работает авторизация?`

### Step 1. Project is indexed in advance

Repository on server:

- `/srv/projects/proj1`

Indexer walks the repo and creates chunks such as:

- `src/auth/jwt_middleware.ts`
- `src/api/login.ts`
- `src/services/session_service.ts`
- `src/config/security.ts`

Each chunk gets:

- text
- path
- line range
- symbol metadata
- embedding vector

All of this is stored in a local index.

### Step 2. User asks a question in Web UI

Input:

`Где и как у нас работает авторизация?`

UI sends the request to the retrieval service, not directly to the LLM.

### Step 3. Retrieval service searches the project

It performs hybrid retrieval:

- semantic search over embeddings
- keyword search over code and file paths

Keyword expansion examples:

- `auth`
- `jwt`
- `token`
- `guard`
- `session`
- `login`

This hybrid approach is better than semantic-only search for codebases.

### Step 4. Retrieval service selects useful context

It chooses top chunks, for example:

- `src/api/login.ts:1-44`
- `src/auth/jwt_middleware.ts:12-68`
- `src/services/session_service.ts:10-91`
- `src/config/security.ts:1-30`

Then it may attach neighbor chunks when necessary:

- previous helper function
- nearby config block
- related type definition

### Step 5. Retrieval service builds the prompt

Prompt structure:

- system instruction
- user question
- retrieved code context with file references
- response format requirement

Example instruction:

- answer only from provided project context
- say when context is insufficient
- cite files and line ranges
- summarize the auth flow in order

### Step 6. LLM generates grounded answer

The model answers using the retrieved code.

Expected answer style:

- auth starts in `src/api/login.ts`
- token creation happens in `src/services/session_service.ts`
- request validation is done in `src/auth/jwt_middleware.ts`
- token ttl and secrets are configured in `src/config/security.ts`

### Step 7. UI shows answer and sources

Web UI should display:

- natural language answer
- source file list
- optional raw retrieved snippets

This makes the answer auditable.

## Minimal v1 Architecture

### Services

1. `llama-server`

- already exists
- keeps serving generation requests

2. `rag-indexer`

- CLI script
- scans repository
- parses files
- builds chunks
- computes embeddings
- writes FAISS index and metadata

3. `rag-api`

- small Python HTTP service
- receives questions
- performs retrieval
- calls `llama-server`
- returns answer and source references

### Data layout

Suggested directories:

- `/srv/projects/proj1`
- `/srv/rag/proj1/matrix.npz`
- `/srv/rag/proj1/vectorizer.joblib`
- `/srv/rag/proj1/chunks.jsonl`
- `/srv/rag/proj1/meta.json`

### Basic APIs

Suggested endpoints:

- `POST /index`
- `POST /ask`
- `GET /projects`
- `GET /health`

Example `POST /ask` payload:

```json
{
  "project": "proj1",
  "question": "Где и как работает авторизация?",
  "model_profile": "lite"
}
```

Example response:

```json
{
  "answer": "Авторизация начинается в ...",
  "sources": [
    {
      "path": "src/auth/jwt_middleware.ts",
      "start_line": 12,
      "end_line": 68
    },
    {
      "path": "src/api/login.ts",
      "start_line": 1,
      "end_line": 44
    }
  ]
}
```

## Why Embeddings Are Needed

Without embeddings:

- search works only on literal matches
- questions like `где у нас авторизация` may miss `jwt middleware validates bearer token`

With embeddings:

- the system finds semantically related code even when names differ

Practical rule:

- do not rely on embeddings alone
- combine embeddings with keyword/path search

For code, hybrid retrieval is the safer default.

## Why A Retrieval Service Is Needed

Without a retrieval service:

- UI would have to know how to search indexes
- UI would have to build prompts
- UI would have to choose files and chunks

That logic should live in one server-side layer.

Retrieval service responsibilities:

- project selection
- retrieval policy
- prompt assembly
- model selection
- source formatting

This keeps the frontend thin and replaceable.

## Suggested v1 Implementation Plan

### Phase 1. Local project QA without vector DB complexity

Implement:

- repo selection
- `rg` keyword search
- simple file chunking
- prompt assembly

Goal:

- prove the UX and usefulness

### Phase 2. Add embeddings and FAISS

Implement:

- code chunks
- embeddings
- semantic retrieval
- hybrid ranking

Goal:

- better recall on big projects

### Phase 3. Improve developer ergonomics

Implement:

- clickable sources in UI
- cached indexing
- project reindex
- optional summaries per file/module

### Phase 4. Optional advanced upgrades

Possible later additions:

- reranking
- symbol graph
- git blame awareness
- issue tracker links
- multiple repositories

## Practical Recommendation For This Server

Best first version:

- keep current `llama-server`
- add a small Python `rag-api`
- use `tree-sitter`
- use `FAISS`
- use hybrid retrieval
- start with one project only

This keeps the system:

- local
- understandable
- debuggable
- cheap to run

It also avoids overbuilding before the workflow proves useful.
