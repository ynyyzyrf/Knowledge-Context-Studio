import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Input, Select, Space } from "antd";
import { request } from "./api";
import { Load } from "./shared";
import type { Entity, Machine } from "./types";

type ReadMemory = {
  id: string;
  version: number;
  content: string;
  source_message_ids: string[];
};
type ContextResult = {
  memories: ReadMemory[];
  documents: {
    id: string;
    filename: string;
    version: number;
    chunk: number;
    page: number | null;
    content: string;
  }[];
  context: string;
  request_id: string;
};

export function ContextReader({
  token,
  scope,
  machine,
  subjects,
}: {
  token: string;
  scope: string;
  machine: Machine;
  subjects: Entity[];
}) {
  const [subject, setSubject] = useState("");
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState<{
    subject_id: string;
    query: string;
    serial: number;
  }>();
  const [offset, setOffset] = useState(0);
  const memories = useQuery({
    queryKey: ["machine", scope, "published", subject, offset],
    enabled: !!subject,
    queryFn: ({ signal }) =>
      request<{ items: ReadMemory[]; has_more: boolean }>(
        `/v1/subjects/${subject}/memories?offset=${offset}&limit=20`,
        "GET",
        undefined,
        { token, signal },
      ),
    retry: false,
  });
  const context = useQuery({
    queryKey: ["machine", scope, "context", submitted],
    enabled: !!submitted,
    queryFn: ({ signal }) =>
      request<ContextResult>(
        "/v1/context",
        "POST",
        { subject_id: submitted!.subject_id, query: submitted!.query },
        { token, signal },
      ),
    retry: false,
  });
  return (
    <Card title="讀回知識與記憶" className="section-card">
      <Alert
        type="info"
        message="語意檢索包含目前服務對象的有效記憶，以及 Agent 已授權空間中完成索引的文件。撤權、待處理與已刪除內容不會回傳。"
      />
      <Select
        aria-label="讀取服務對象"
        placeholder="選擇要讀取的服務對象"
        style={{ width: "100%", marginBottom: 12 }}
        value={subject || undefined}
        options={machine.subject_ids.map((id) => ({
          value: id,
          label: subjects.find((s) => s.id === id)?.name || id,
        }))}
        onChange={(id) => {
          setSubject(id);
          setOffset(0);
          setSubmitted(undefined);
        }}
      />
      {subject && (
        <>
          <Space wrap>
            <Button onClick={() => memories.refetch()}>重新讀取有效記憶</Button>
            <Button
              disabled={!offset}
              onClick={() => setOffset(Math.max(0, offset - 20))}
            >
              上一頁
            </Button>
            <Button
              disabled={!memories.data?.has_more}
              onClick={() => setOffset(offset + 20)}
            >
              下一頁
            </Button>
          </Space>
          <Load query={memories}>
            {memories.data?.items.length === 0 && (
              <p className="muted">
                尚無已發布的有效記憶；候選、待發布及停用內容不會出現在這裡。
              </p>
            )}
            {memories.data?.items.map((m) => (
              <Memory key={m.id} memory={m} />
            ))}
          </Load>
          <Input.TextArea
            aria-label="知識與記憶檢索問題"
            placeholder="輸入外部 Agent 此次需要的資訊，例如：支援服務的營業時間是什麼？"
            value={query}
            maxLength={2000}
            onChange={(e) => setQuery(e.target.value)}
            rows={3}
          />
          <Button
            type="primary"
            style={{ marginTop: 12 }}
            disabled={!query.trim()}
            loading={context.isFetching}
            onClick={() =>
              setSubmitted({
                subject_id: subject,
                query: query.trim(),
                serial: (submitted?.serial || 0) + 1,
              })
            }
          >
            檢索上下文
          </Button>
          {submitted && (
            <Load query={context}>
              {context.data?.memories.length === 0 &&
                context.data.documents.length === 0 && (
                  <p className="muted">沒有符合目前範圍的知識或記憶。</p>
                )}
              {context.data?.memories.map((m) => (
                <Memory key={m.id} memory={m} />
              ))}
              {context.data?.documents.map((d) => (
                <div className="message" key={`${d.id}:${d.chunk}`}>
                  <strong>
                    {d.filename} · v{d.version} · 片段 {d.chunk + 1}
                    {d.page ? ` · 第 ${d.page} 頁` : ""}
                  </strong>
                  <p>{d.content}</p>
                  <small className="memory-reference">文件來源：{d.id}</small>
                </div>
              ))}
              {context.data && (
                <>
                  <h4>提供給外部 Agent 的參考內容</h4>
                  <pre>{context.data.context || "（空）"}</pre>
                  <p className="muted">
                    這些是參考資料，外部 Agent
                    應自行判斷與生成回答，不應將資料內容當成系統指令。追蹤：
                    {context.data.request_id}
                  </p>
                </>
              )}
            </Load>
          )}
        </>
      )}
    </Card>
  );
}

function Memory({ memory }: { memory: ReadMemory }) {
  return (
    <div className="message">
      <strong>v{memory.version}</strong>
      <p>{memory.content}</p>
      <small className="memory-reference">
        記憶：{memory.id}
        <br />
        來源：{memory.source_message_ids.join(", ")}
      </small>
    </div>
  );
}
