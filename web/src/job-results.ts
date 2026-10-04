import type { Job } from "./types";

export const resultLabels: Record<string, string> = {
  waiting: "等待處理",
  processing: "提取中",
  indexing: "索引處理中",
  ready: "已可檢索",
  review_required: "待審核",
  no_changes: "沒有新增記憶",
  failed: "處理失敗",
  created: "已入庫",
  deduplicated: "已去重",
  ignored: "已略過",
};

export function jobIsRunning(job: Job): boolean {
  return (
    ["pending", "running", "retry"].includes(job.state) ||
    job.result?.pipeline_state === "indexing"
  );
}

export function jobSummary(job: Job): string {
  if (job.result?.reason === "no_durable_facts") return "沒有可存的長期記憶";
  return (
    resultLabels[job.result?.pipeline_state || ""] ||
    (job.state === "pending" ? "等待處理" : job.state)
  );
}
