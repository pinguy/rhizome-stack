import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_TIMEOUT_MS = 30_000;
const DEFAULT_MAX_RESPONSE_BYTES = 1024 * 1024;

export class RhizomeServer {
  constructor(cfg, scriptPath = new URL("./rhizome_memory_server.py", import.meta.url)) {
    this.cfg = cfg;
    this.scriptPath = path.resolve(scriptPath instanceof URL ? fileURLToPath(scriptPath) : String(scriptPath));
    this.proc = null;
    this.buf = "";
    this.queue = [];
    this.terminateCurrent = null;
    this.healthy = false;
    this.lastError = "not started";
  }

  finishPending(message) {
    while (this.queue.length) {
      const pending = this.queue.shift();
      clearTimeout(pending.timer);
      pending.resolve({ ok: false, error: message, unavailable: true });
    }
  }

  start() {
    if (this.proc) return;
    if (!fs.existsSync(this.scriptPath)) {
      throw new Error(`rhizome_memory_server.py not found at ${this.scriptPath}`);
    }

    const proc = spawn(this.cfg.pythonPath, [this.scriptPath], {
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
    this.proc = proc;
    this.healthy = false;
    this.lastError = "starting";

    let terminal = false;
    const terminate = (message, kill = false) => {
      if (terminal) return;
      terminal = true;
      if (this.proc === proc) {
        this.proc = null;
        this.terminateCurrent = null;
        this.buf = "";
        this.healthy = false;
        this.lastError = message;
        this.finishPending(message);
      }
      if (kill && !proc.killed) proc.kill("SIGTERM");
    };
    this.terminateCurrent = terminate;

    proc.stdout.setEncoding("utf8");
    proc.stdout.on("data", (chunk) => {
      if (terminal || this.proc !== proc) return;
      this.buf += chunk;
      const maxBytes = Number(this.cfg.maxResponseBytes ?? DEFAULT_MAX_RESPONSE_BYTES);
      if (Buffer.byteLength(this.buf, "utf8") > maxBytes) {
        terminate(`rhizome server response exceeded ${maxBytes} bytes`, true);
        return;
      }
      while (true) {
        const idx = this.buf.indexOf("\n");
        if (idx === -1) break;
        const line = this.buf.slice(0, idx);
        this.buf = this.buf.slice(idx + 1);
        if (!line.trim()) continue;
        if (Buffer.byteLength(line, "utf8") > maxBytes) {
          terminate(`rhizome server response exceeded ${maxBytes} bytes`, true);
          return;
        }
        let parsed;
        try {
          parsed = JSON.parse(line);
        } catch {
          parsed = { ok: false, error: "bad json from rhizome server", raw: line };
        }
        // Receiving well-formed JSON is not proof that the worker succeeded.
        // A live child can answer with {ok:false} when its index is unavailable.
        this.healthy = parsed !== null && typeof parsed === "object" && !Array.isArray(parsed) && parsed.ok === true;
        this.lastError = this.healthy
          ? null
          : (typeof parsed?.error === "string" && parsed.error
              ? parsed.error
              : "rhizome server returned an unsuccessful response");
        const pending = this.queue.shift();
        if (pending) {
          clearTimeout(pending.timer);
          pending.resolve(parsed);
        }
      }
    });

    proc.stderr.setEncoding("utf8");
    proc.stderr.on("data", () => {
      // intentionally quiet; callers receive a bounded unavailable result
    });
    proc.on("error", (error) => terminate(`rhizome server error: ${error.message}`));
    proc.on("exit", (code, signal) => {
      const detail = signal ? `signal ${signal}` : `code ${code}`;
      terminate(`rhizome server exited (${detail})`);
    });
  }

  request(payload) {
    try {
      this.start();
    } catch (error) {
      const message = `rhizome server unavailable: ${error instanceof Error ? error.message : String(error)}`;
      this.healthy = false;
      this.lastError = message;
      return Promise.resolve({ ok: false, error: message, unavailable: true });
    }
    const proc = this.proc;
    if (!proc) {
      return Promise.resolve({ ok: false, error: "rhizome server unavailable", unavailable: true });
    }
    return new Promise((resolve) => {
      const timeoutMs = Number(this.cfg.requestTimeoutMs ?? DEFAULT_TIMEOUT_MS);
      const pending = { resolve, timer: null };
      pending.timer = setTimeout(() => {
        this.terminateCurrent?.(`rhizome server request timed out after ${timeoutMs} ms`, true);
      }, timeoutMs);
      this.queue.push(pending);
      proc.stdin.write(JSON.stringify(payload) + "\n", (error) => {
        if (error) this.terminateCurrent?.(`rhizome server stdin error: ${error.message}`, true);
      });
    });
  }

  health() {
    return {
      available: Boolean(this.proc && this.healthy),
      error: this.lastError,
    };
  }

  stop() {
    const proc = this.proc;
    if (!proc) return;
    this.terminateCurrent?.("rhizome server stopped", true);
  }
}
