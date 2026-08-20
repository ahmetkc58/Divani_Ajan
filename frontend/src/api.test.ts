import { afterEach, describe, expect, it, vi } from "vitest";

import { api, waitForJob } from "./api";
import type { Job } from "./types";

const completedJob: Job = {
  id: "job-1",
  job_type: "ocr",
  status: "succeeded",
  progress: 100,
  stage: "Hazır",
  result_id: "result-1",
  created_at: "2026-08-20T10:00:00Z",
  updated_at: "2026-08-20T10:00:01Z",
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("API istemcisi", () => {
  it("tamamlanan işi döndürür ve ilerlemeyi bildirir", async () => {
    vi.spyOn(api, "job").mockResolvedValue(completedJob);
    const onProgress = vi.fn();

    const result = await waitForJob("job-1", onProgress);

    expect(result).toEqual(completedJob);
    expect(onProgress).toHaveBeenCalledWith(completedJob);
  });

  it("sunucunun hata ayrıntısını kullanıcıya taşır", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Ollama servisine ulaşılamıyor." }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(api.health()).rejects.toThrow("Ollama servisine ulaşılamıyor.");
  });
});
