import type { OpenClawPluginApi } from "openclaw/plugin-sdk";
import { emptyPluginConfigSchema } from "openclaw/plugin-sdk";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { listMemoryHostPublicArtifacts } from "openclaw/plugin-sdk/memory-host-core";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

const OPENCLAW_DIST = process.env.OPENCLAW_DIST ?? path.join(os.homedir(), ".npm-global/lib/node_modules/openclaw/dist");
let recallTrackerPromise: Promise<any> | null = null;

async function loadRecallTracker() {
  if (!recallTrackerPromise) {
    recallTrackerPromise = (async () => {
      const candidates = fs.readdirSync(OPENCLAW_DIST)
        .filter((name) => /^short-term-promotion-.*\.js$/.test(name));
      for (const name of candidates) {
        const loaded = await import(path.join(OPENCLAW_DIST, name));
        if (typeof loaded.recordShortTermRecalls === "function") {
          return loaded.recordShortTermRecalls;
        }
      }
      throw new Error("OpenClaw short-term recall tracker export was not found");
    })();
  }
  return recallTrackerPromise;
}

async function trackSurfacedMarkdownRecalls(workspaceDir: string, query: string, results: any[]) {
  const markdownResults = results.filter((result) =>
    result?.source === "memory" &&
    typeof result?.path === "string" &&
    /^memory\/(?:[^/]+\/)*\d{4}-\d{2}-\d{2}(?:-[^/]+)?\.md$/.test(result.path),
  );
  if (!query.trim() || markdownResults.length === 0) return;
  const recordShortTermRecalls = await loadRecallTracker();
  await recordShortTermRecalls({
    workspaceDir,
    query,
    results: markdownResults,
    timezone: process.env.TZ || "UTC",
  });
}

const MARKDOWN_STOPWORDS = new Set([
  "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "did",
  "do", "does", "for", "from", "had", "has", "have", "how", "i", "if", "in",
  "is", "it", "its", "me", "my", "not", "of", "on", "or", "our", "should",
  "so", "that", "the", "their", "them", "there", "these", "they", "this", "to",
  "was", "we", "were", "what", "when", "where", "which", "who", "why", "will",
  "with", "you", "your",
]);

function lexicalTokens(value: string) {
  return new Set(
    String(value)
      .toLowerCase()
      .match(/[a-z0-9]+/g)
      ?.map((token) => token.replace(/(?<=\d)(st|nd|rd|th)$/, ""))
      .filter((token) => !MARKDOWN_STOPWORDS.has(token) && (token.length > 2 || /^\d+$/.test(token))) ?? [],
  );
}

function searchCuratedMarkdown(workspaceDir: string, query: string, limit: number) {
  const roots = [
    path.join(workspaceDir, "MEMORY.md"),
    // Memories authored in Open WebUI's native panel are mirrored here by
    // scripts/sync_openwebui_memory.py --pull, so OpenClaw can see them too.
    path.join(workspaceDir, "memory", "shared-openwebui.md"),
    ...(() => {
      const dailyDir = path.join(workspaceDir, "memory");
      try {
        return fs.readdirSync(dailyDir)
          .filter((name) => /^\d{4}-\d{2}-\d{2}\.md$/.test(name))
          .map((name) => path.join(dailyDir, name));
      } catch {
        return [];
      }
    })(),
  ];
  const queryTokens = lexicalTokens(query);
  if (!queryTokens.size) return [];

  const results: any[] = [];
  for (const filePath of roots) {
    let content: string;
    try {
      content = fs.readFileSync(filePath, "utf8");
    } catch {
      continue;
    }
    const lines = content.split(/\r?\n/);
    let start = 0;
    for (let i = 0; i <= lines.length; i += 1) {
      const startsBlock = i < lines.length && (/^#{1,6}\s/.test(lines[i]) || /^[-*]\s/.test(lines[i]));
      const boundary = i === lines.length || lines[i].trim() === "" || (startsBlock && i > start);
      if (!boundary) continue;
      const end = i;
      const chunkStart = start;
      const chunk = lines.slice(start, end).join("\n").trim();
      start = startsBlock ? i : i + 1;
      if (!chunk) continue;

      const chunkTokens = lexicalTokens(chunk);
      const matched = [...queryTokens].filter((token) => chunkTokens.has(token)).length;
      const minimumMatches = queryTokens.size <= 3 ? 1 : 2;
      if (matched < minimumMatches) continue;
      const coverage = matched / queryTokens.size;
      const density = matched / Math.max(matched, Math.sqrt(chunkTokens.size));
      // Curated Markdown is authoritative continuity, so a strong lexical match
      // must beat a vaguely semantic historical chat. Weak matches remain below
      // good FAISS results rather than receiving a blanket source bonus.
      const relPath = path.relative(workspaceDir, filePath);
      const authorityPrior = relPath === "MEMORY.md" ? 0.12 : 0.02;
      const score = Math.min(0.98, 0.22 + 0.62 * coverage + 0.10 * density + authorityPrior);
      results.push({
        path: relPath,
        startLine: chunkStart + 1,
        endLine: end,
        score,
        snippet: chunk.slice(0, 1200),
        source: "memory",
        authority: relPath === "MEMORY.md" ? "curated" : "daily",
      });
    }
  }
  // Below this point lexical overlap is too weak to justify displacing a
  // semantic archive result. This gate is what keeps the fallback hybrid.
  return results
    .filter((result) => result.score >= 0.52)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit);
}

const MemorySearchSchema = {
  type: "object",
  additionalProperties: false,
  properties: {
    query: { type: "string" },
    maxResults: { type: "number" },
    minScore: { type: "number" },
  },
  required: ["query"],
} as const;

const MemoryGetSchema = {
  type: "object",
  additionalProperties: false,
  properties: {
    path: { type: "string" },
    from: { type: "number" },
    lines: { type: "number" },
  },
  required: ["path"],
} as const;

type RhizomeConfig = {
  enabled?: boolean;
  pythonPath?: string;
  baseDir?: string;
  indexPath?: string;
  textsPath?: string;
  metadataPath?: string;
  embedModel?: string;
  device?: "auto" | "cuda" | "cpu";
  topK?: number;
  snippetMaxChars?: number;
};

function resolveCfg(raw: unknown): Required<RhizomeConfig> {
  const cfg = (raw || {}) as RhizomeConfig;
  const baseDir = cfg.baseDir || path.join(os.homedir(), ".local/share/rhizome-stack/memory/archive");
  return {
    enabled: cfg.enabled ?? true,
    pythonPath: cfg.pythonPath || path.join(os.homedir(), ".local/share/rhizome-stack/venvs/memory/bin/python"),
    baseDir,
    indexPath: cfg.indexPath || path.join(baseDir, "memory.index"),
    textsPath: cfg.textsPath || path.join(baseDir, "memory_texts.npy"),
    metadataPath: cfg.metadataPath || path.join(baseDir, "memory_metadata.pkl"),
    embedModel: cfg.embedModel || "sentence-transformers/all-MiniLM-L6-v2",
    device: cfg.device || "auto",
    topK: cfg.topK ?? 10,
    snippetMaxChars: cfg.snippetMaxChars ?? 700,
  };
}

class RhizomeServer {
  private proc: ChildProcessWithoutNullStreams | null = null;
  private buf = "";
  private queue: Array<(msg: any) => void> = [];

  constructor(private readonly cfg: Required<RhizomeConfig>) {}

  start() {
    if (this.proc) return;

    const script = path.resolve(path.dirname(new URL(import.meta.url).pathname), "./rhizome_memory_server.py");
    if (!fs.existsSync(script)) {
      throw new Error(`rhizome_memory_server.py not found at ${script}`);
    }

    this.proc = spawn(this.cfg.pythonPath, [script], {
      stdio: ["pipe", "pipe", "pipe"],
      env: {
        ...process.env,
        RHIZOME_BASE_DIR: this.cfg.baseDir,
        RHIZOME_INDEX: this.cfg.indexPath,
        RHIZOME_TEXTS: this.cfg.textsPath,
        RHIZOME_META: this.cfg.metadataPath,
        RHIZOME_EMBED_MODEL: this.cfg.embedModel,
        RHIZOME_DEVICE: this.cfg.device,
        MALLOC_ARENA_MAX: "2",
        MALLOC_TRIM_THRESHOLD_: "131072",
        MALLOC_MMAP_THRESHOLD_: "131072",
        OMP_NUM_THREADS: "4",
        MKL_NUM_THREADS: "4",
        OPENBLAS_NUM_THREADS: "4",
        NUMEXPR_NUM_THREADS: "4",
      },
    });

    this.proc.stdout.setEncoding("utf8");
    this.proc.stdout.on("data", (chunk: string) => {
      this.buf += chunk;
      while (true) {
        const idx = this.buf.indexOf("\n");
        if (idx === -1) break;
        const line = this.buf.slice(0, idx);
        this.buf = this.buf.slice(idx + 1);
        if (!line.trim()) continue;
        let parsed: any;
        try {
          parsed = JSON.parse(line);
        } catch {
          parsed = { ok: false, error: "bad json from rhizome server", raw: line };
        }
        const fn = this.queue.shift();
        if (fn) fn(parsed);
      }
    });

    this.proc.stderr.setEncoding("utf8");
    this.proc.stderr.on("data", (_chunk: string) => {
      // intentionally quiet
    });

    this.proc.on("exit", () => {
      this.proc = null;
      while (this.queue.length) {
        const fn = this.queue.shift();
        fn?.({ ok: false, error: "rhizome server exited" });
      }
    });
  }

  request(payload: any): Promise<any> {
    this.start();
    return new Promise((resolve) => {
      this.queue.push(resolve);
      this.proc!.stdin.write(JSON.stringify(payload) + "\n");
    });
  }

  stop() {
    const proc = this.proc;
    if (!proc) return;
    this.proc = null;
    this.buf = "";
    while (this.queue.length) {
      const fn = this.queue.shift();
      fn?.({ ok: false, error: "rhizome server stopped" });
    }
    proc.stdin.end();
    if (!proc.killed) proc.kill("SIGTERM");
  }
}

function toMemoryResults(resp: any, cfg: Required<RhizomeConfig>, maxResults?: number, minScore?: number) {
  const k = Math.max(1, Math.min(50, maxResults ?? cfg.topK));
  return (resp?.ok ? resp.results : [])
    .map((r: any) => {
      const score = Number(r.score ?? 0);
      return {
        path: `rhizome://${r.idx}`,
        startLine: 0,
        endLine: 0,
        score,
        vectorScore: score,
        snippet: String(r.snippet ?? ""),
        source: "memory" as const,
        citation: `rhizome://${r.idx}`,
      };
    })
    .filter((r: any) => !minScore || r.score >= minScore)
    .slice(0, k);
}

class RhizomeMemoryManager {
  constructor(
    private readonly server: RhizomeServer,
    private readonly cfg: Required<RhizomeConfig>,
  ) {}

  async search(query: string, opts?: { maxResults?: number; minScore?: number }) {
    const k = Math.max(1, Math.min(50, opts?.maxResults ?? this.cfg.topK));
    const resp = await this.server.request({
      type: "search",
      query,
      k,
      snippetMaxChars: this.cfg.snippetMaxChars,
    });
    return toMemoryResults(resp, this.cfg, opts?.maxResults, opts?.minScore);
  }

  async readFile(params: { relPath: string; from?: number; lines?: number }) {
    const match = String(params.relPath ?? "").match(/^rhizome:\/\/(\d+)$/);
    if (!match) {
      return { path: params.relPath, text: "", truncated: false, from: params.from, lines: params.lines };
    }
    const resp = await this.server.request({ type: "get", idx: Number(match[1]) });
    return {
      path: params.relPath,
      text: resp?.ok ? String(resp.text ?? "") : "",
      truncated: false,
      from: params.from,
      lines: params.lines,
    };
  }

  status() {
    return {
      backend: "builtin" as const,
      provider: "rhizome-faiss",
      model: this.cfg.embedModel,
      workspaceDir: this.cfg.baseDir,
      sources: ["memory" as const],
      vector: { enabled: true, available: true },
    };
  }

  async sync() {}

  getCachedEmbeddingAvailability() {
    return { ok: true, checked: true, cached: true, checkedAtMs: Date.now() };
  }

  async probeEmbeddingAvailability() {
    return { ok: true, checked: true, checkedAtMs: Date.now() };
  }

  async probeVectorStoreAvailability() {
    return true;
  }

  async probeVectorAvailability() {
    return true;
  }
}

function buildRhizomePromptSection({ availableTools }: { availableTools: Set<string> }) {
  if (!availableTools.has("memory_search") && !availableTools.has("memory_get")) return [];
  return [
    "## Memory Recall",
    "Before answering about prior conversations, preferences, decisions, or remembered context, use memory_search. It combines local Markdown memory with RhizomeML FAISS recall.",
    "",
  ];
}

const plugin = definePluginEntry({
  id: "memory-rhizome",
  name: "Memory (Rhizome)",
  description: "Hybrid memory_search: OpenClaw Markdown + RhizomeML FAISS.",
  kind: "memory" as const,
  configSchema: emptyPluginConfigSchema,
  register(api: OpenClawPluginApi) {
    const managers = new Map<string, RhizomeMemoryManager>();
    const servers = new Map<string, RhizomeServer>();
    const configKey = (cfg: Required<RhizomeConfig>) => JSON.stringify({
        pythonPath: cfg.pythonPath,
        baseDir: cfg.baseDir,
        indexPath: cfg.indexPath,
        textsPath: cfg.textsPath,
        metadataPath: cfg.metadataPath,
        embedModel: cfg.embedModel,
        device: cfg.device,
        topK: cfg.topK,
        snippetMaxChars: cfg.snippetMaxChars,
      });
    const getServer = (cfg: Required<RhizomeConfig>) => {
      const key = configKey(cfg);
      let server = servers.get(key);
      if (!server) {
        server = new RhizomeServer(cfg);
        servers.set(key, server);
      }
      return server;
    };
    const getManager = (rootConfig: any) => {
      const rawPluginCfg = rootConfig?.plugins?.entries?.["memory-rhizome"]?.config;
      const cfg = resolveCfg(rawPluginCfg);
      const key = configKey(cfg);
      let manager = managers.get(key);
      if (!manager) {
        manager = new RhizomeMemoryManager(getServer(cfg), cfg);
        managers.set(key, manager);
      }
      return manager;
    };

    api.registerMemoryCapability({
      promptBuilder: buildRhizomePromptSection,
      publicArtifacts: {
        async listArtifacts(params: any) {
          return listMemoryHostPublicArtifacts({ cfg: params.cfg });
        },
      },
      runtime: {
        async getMemorySearchManager(params: any) {
          return { manager: getManager(params.cfg) };
        },
        resolveMemoryBackendConfig() {
          return { backend: "builtin" as const };
        },
        async closeAllMemorySearchManagers() {
          managers.clear();
          for (const server of servers.values()) server.stop();
          servers.clear();
        },
      },
    });

    api.registerTool(
      (ctx) => {
        const baseTools = (api.runtime as any)?.tools;
        const baseSearch = baseTools?.createMemorySearchTool?.({
          config: ctx.config,
          agentSessionKey: ctx.sessionKey,
        });
        const baseGet = baseTools?.createMemoryGetTool?.({
          config: ctx.config,
          agentSessionKey: ctx.sessionKey,
        });

        const rawPluginCfg = (ctx.config as any)?.plugins?.entries?.["memory-rhizome"]?.config;
        const cfg = resolveCfg(rawPluginCfg);
        if (!cfg.enabled) {
          return baseSearch && baseGet ? [baseSearch, baseGet] : null;
        }

        const server = getServer(cfg);

        const hybridSearch = {
          label: "Memory Search",
          name: "memory_search",
          description:
            "Hybrid recall: searches OpenClaw Markdown memory plus RhizomeML FAISS index (books + historical chats).",
          parameters: MemorySearchSchema,
          execute: async (_toolCallId: string, params: any) => {
            const query = String(params.query ?? "");
            const maxResults = typeof params.maxResults === "number" ? params.maxResults : undefined;
            const minScore = typeof params.minScore === "number" ? params.minScore : undefined;

            // 1) base results (markdown memory)
            let basePayload: any = { results: [], disabled: true };
            if (baseSearch) {
              const raw = await (baseSearch as any).execute(_toolCallId, { query, maxResults, minScore });
              try {
                basePayload = JSON.parse(raw?.content?.[0]?.text ?? "{}") || basePayload;
              } catch {
                // ignore
              }
            }
            // Some OpenClaw runtimes do not expose the builtin Markdown tool to
            // a memory-slot plugin. Never silently degrade "hybrid" recall to
            // FAISS-only: use a conservative lexical fallback over MEMORY.md
            // and dated daily notes.
            if (!(basePayload.results || []).length) {
              const workspaceDir = path.dirname(cfg.baseDir);
              basePayload = {
                results: searchCuratedMarkdown(
                  workspaceDir,
                  query,
                  Math.max(10, maxResults ?? cfg.topK),
                ),
                provider: "rhizome-markdown-fallback",
              };
            }

            // 2) rhizome results (FAISS)
            const looksDyad = (() => {
              const q = query.toLowerCase();
              return (
                /\b(remember|we talked|we spoke|last time|previously|earlier|you said|i said|did i say|did you say|our chat|dyad)\b/.test(q) ||
                /\b(you can probably tell|long ass time|over the years)\b/.test(q)
              );
            })();

            const k = Math.max(1, Math.min(50, maxResults ?? cfg.topK));
            const candidateK = looksDyad ? Math.max(k, 30) : k;
            const snippetMax = looksDyad ? Math.max(cfg.snippetMaxChars, 1200) : cfg.snippetMaxChars;

            const resp = await server.request({
              type: "search",
              query,
              k: candidateK,
              snippetMaxChars: snippetMax,
            });

            const nowSec = Date.now() / 1000;
            const scoreAdjusted = (base: number, meta: any) => {
              let s = base;
              const source = String(meta?.source ?? "");
              const author = String(meta?.author ?? "");

              // Dyad bias when the prompt looks like dyad recall.
              if (looksDyad) {
                if (source === "conversation") s += 0.25;
                if (author === "user" || author === "assistant") s += 0.1;
                if (author === "tool") s -= 0.2;

                const ts = Number(meta?.timestamp);
                if (Number.isFinite(ts) && ts > 0) {
                  // Recency boost with ~60 day half-life
                  const ageDays = Math.max(0, (nowSec - ts) / 86400);
                  const boost = 0.12 * Math.exp(-ageDays / 60);
                  s += boost;
                }
              }

              return s;
            };

            const rhizomeResults = (resp?.ok ? resp.results : [])
              .map((r: any) => {
                const baseScore = Number(r.score ?? 0);
                const meta = r.meta || {};
                const score = scoreAdjusted(baseScore, meta);

                // Add a tiny header for dyad prompts so the model can use it safely.
                const header = looksDyad && meta?.source === "conversation"
                  ? `[dyad:${meta.author ?? "?"} convo:${meta.conversation_id ?? "?"}] `
                  : "";

                return {
                  path: `rhizome://${r.idx}`,
                  startLine: 0,
                  endLine: 0,
                  score,
                  vectorScore: Number(r.vectorScore ?? baseScore),
                  usefulness: r.usefulness || undefined,
                  snippet: header + String(r.snippet ?? ""),
                  source: "memory",
                };
              })
              // For dyad prompts, prefer conversation entries; keep non-conversation as fallback.
              .sort((a: any, b: any) => (b.score ?? 0) - (a.score ?? 0))
              .filter((r: any) => !minScore || r.score >= minScore)
              .slice(0, k);

            const merged = [...(basePayload.results || []), ...rhizomeResults]
              .sort((a: any, b: any) => (b.score ?? 0) - (a.score ?? 0))
              .slice(0, maxResults ?? cfg.topK);

            // memory-rhizome owns the live memory_search tool, so memory-core's
            // builtin wrapper never sees these surfaced Markdown recalls.
            // Feed only dated Markdown hits into its existing tracker; FAISS
            // archive rows and MEMORY.md itself are deliberately excluded.
            await trackSurfacedMarkdownRecalls(path.dirname(cfg.baseDir), query, merged);

            return {
              content: [
                {
                  type: "text",
                  text: JSON.stringify({
                    results: merged,
                    provider: basePayload.provider || "hybrid",
                    model: basePayload.model || "rhizome+markdown",
                    fallback: basePayload.fallback,
                    rhizome: {
                      enabled: true,
                      device: cfg.device,
                      embedModel: cfg.embedModel,
                      ranker: resp?.ranker,
                    },
                  }),
                },
              ],
            };
          },
        };

        const hybridGet = {
          label: "Memory Get",
          name: "memory_get",
          description: "Read memory from OpenClaw Markdown paths or rhizome://<id> entries.",
          parameters: MemoryGetSchema,
          execute: async (_toolCallId: string, params: any) => {
            const p = String(params.path ?? "");
            const from = typeof params.from === "number" ? params.from : undefined;
            const lines = typeof params.lines === "number" ? params.lines : undefined;

            if (p.startsWith("rhizome://")) {
              const idxStr = p.replace("rhizome://", "");
              const idx = Number.parseInt(idxStr, 10);
              const resp = await server.request({ type: "get", idx });
              if (!resp?.ok) {
                return {
                  content: [
                    {
                      type: "text",
                      text: JSON.stringify({ path: p, text: "", disabled: true, error: resp?.error || "failed" }),
                    },
                  ],
                };
              }
              let text = String(resp.text ?? "");
              if (from !== undefined || lines !== undefined) {
                const arr = text.split(/\r?\n/);
                const start = Math.max(1, from ?? 1);
                const take = Math.max(1, lines ?? 200);
                text = arr.slice(start - 1, start - 1 + take).join("\n");
              }
              return {
                content: [
                  {
                    type: "text",
                    text: JSON.stringify({
                      path: p,
                      text,
                      meta: resp.meta || {},
                    }),
                  },
                ],
              };
            }

            if (!baseGet) {
              return {
                content: [
                  {
                    type: "text",
                    text: JSON.stringify({ path: p, text: "", disabled: true, error: "base memory_get unavailable" }),
                  },
                ],
              };
            }
            return (baseGet as any).execute(_toolCallId, { path: p, from, lines });
          },
        };

        return [hybridSearch as any, hybridGet as any];
      },
      { names: ["memory_search", "memory_get"] },
    );
  },
});

export default plugin;
