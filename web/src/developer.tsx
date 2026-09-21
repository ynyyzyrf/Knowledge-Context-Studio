import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Input, Select, Space, Table, Tag } from "antd";
import { ApiError, request } from "./api";
import {
  Heading,
  Load,
  Problem,
  Status,
  useData,
  useForms,
  useWorkspace,
  when,
} from "./shared";
import type {
  Conversation,
  Entity,
  Items,
  Job,
  Machine,
  Message,
} from "./types";
export function Developer() {
  const { tenant, token, setToken } = useWorkspace();
  const [entry, setEntry] = useState("");
  const [session, setSession] = useState("");
  const [after, setAfter] = useState(0);
  const [job, setJob] = useState("");
  const [error, setError] = useState<unknown>();
  const qc = useQueryClient();
  const forms = useForms();
  const scope = useMemo(() => crypto.randomUUID(), [token]);
  const machine = useQuery({
    queryKey: ["machine", scope, "identity"],
    enabled: !!token,
    retry: false,
    queryFn: async ({ signal }) => {
      const value = await request<Machine>("/v1/agent/me", "GET", undefined, {
        token,
        signal,
      });
      if (value.tenant_id !== tenant.tenant_id)
        throw new ApiError(403, "憑證不屬於目前團隊，請切換團隊或更換憑證");
      return value;
    },
  });
  const connected = !!token && !!machine.data && !machine.error;
  const subjects = useData<Items<Entity>>(
    `/agents/${machine.data?.agent_id}/subjects`,
    connected,
  );
  const sessions = useQuery({
    queryKey: ["machine", scope, "sessions"],
    enabled: connected,
    retry: false,
    queryFn: ({ signal }) =>
      request<Items<Conversation>>("/v1/sessions?limit=100", "GET", undefined, {
        token,
        signal,
      }),
  });
  const messages = useQuery({
    queryKey: ["machine", scope, "messages", session, after],
    enabled: connected && !!session,
    retry: false,
    queryFn: ({ signal }) =>
      request<Items<Message>>(
        `/v1/sessions/${session}/messages?after_sequence=${after}&limit=50`,
        "GET",
        undefined,
        { token, signal },
      ),
  });
  const jobStatus = useQuery({
    queryKey: ["machine", scope, "job", job],
    enabled: connected && !!job,
    retry: false,
    queryFn: ({ signal }) =>
      request<Job>(`/v1/jobs/${job}`, "GET", undefined, { token, signal }),
    refetchInterval: (q) =>
      q.state.data &&
      ["pending", "running", "retry"].includes(q.state.data.state)
        ? 3000
        : false,
    refetchIntervalInBackground: false,
  });
  useEffect(() => {
    setSession("");
    setJob("");
    setAfter(0);
    return () => {
      qc.cancelQueries({ queryKey: ["machine", scope] });
      qc.removeQueries({ queryKey: ["machine", scope] });
    };
  }, [scope, qc]);
  const send = async <T,>(path: string, body?: unknown) => {
    if (!connected) throw new ApiError(401, "請先接入有效憑證");
    const result = await request<T>(path, "POST", body, { token });
    await qc.invalidateQueries({ queryKey: ["machine", scope] });
    return result;
  };
  const newSession = () => {
    const key = crypto.randomUUID();
    forms.open({
      title: "建立測試會話",
      note: "此操作會建立真實會話資料，綁定後不能更換服務對象。",
      fields: [
        {
          name: "subject_id",
          label: "已授權服務對象",
          type: "select",
          options: machine.data?.subject_ids.map((id) => ({
            value: id,
            label: subjects.data?.items.find((s) => s.id === id)?.name || id,
          })),
        },
      ],
      submit: async (v) => {
        const row = await send<Conversation>("/v1/sessions", {
          ...v,
          idempotency_key: key,
        });
        setSession(row.id);
        setAfter(0);
      },
    });
  };
  const addMessage = () => {
    const id = crypto.randomUUID();
    forms.open({
      title: "錄入會話訊息",
      note: "模擬外部系統提交訊息；平台不會自動產生 Agent 回答。",
      fields: [
        {
          name: "role",
          label: "訊息來源",
          type: "select",
          options: [
            { value: "user", label: "用戶原始訊息" },
            { value: "assistant", label: "外部 Agent 已產生的訊息" },
          ],
        },
        { name: "content", label: "內容", type: "textarea", max: 32000 },
      ],
      values: { role: "user" },
      submit: (v) =>
        send(`/v1/sessions/${session}/messages`, { ...v, message_id: id }),
    });
  };
  const commit = () => {
    const key = crypto.randomUUID();
    forms.open({
      title: "提交記憶提取？",
      note: "會呼叫已配置的真實模型並可能產生費用，結果進入待審候選區。",
      fields: [],
      submit: async () => {
        const result = await send<Job>(`/v1/sessions/${session}/commit`, {
          idempotency_key: key,
        });
        setJob(result.id);
      },
    });
  };
  return (
    <>
      <Heading
        title="API 接入測試"
        note="開發者工具：驗證外部 Agent 與平台的 API 契約，不執行或託管 Agent。"
      />
      <Alert
        className="section-note"
        type="info"
        showIcon
        message="操作會寫入真實資料。憑證只保留於本頁工作階段，重新整理或切換團隊後需重新接入。"
      />
      <Card title="接入身份" className="section-card">
        {connected ? (
          <>
            <Space wrap>
              <Tag color="green">已驗證</Tag>
              <span>Agent：{machine.data!.agent_id}</span>
              <Button
                onClick={() => {
                  setToken("");
                  setEntry("");
                }}
              >
                中斷接入
              </Button>
              <Button onClick={() => machine.refetch()}>重新驗證</Button>
            </Space>
            <p className="muted">
              可用服務對象 {machine.data!.subject_ids.length} 個 · 授權空間{" "}
              {machine.data!.space_ids.length} 個
            </p>
          </>
        ) : (
          <Space.Compact style={{ width: "100%" }}>
            <Input.Password
              aria-label="Agent 接入憑證"
              placeholder="貼上產品 Agent 憑證（不是模型 API 金鑰）"
              autoComplete="off"
              value={entry}
              onChange={(e) => setEntry(e.target.value)}
            />
            <Button
              type="primary"
              loading={machine.isFetching}
              disabled={!entry.trim()}
              onClick={() => {
                if (entry.trim() === token) void machine.refetch();
                else setToken(entry.trim());
                setEntry("");
                setError(null);
              }}
            >
              驗證接入
            </Button>
          </Space.Compact>
        )}
        {machine.error ? <Problem error={machine.error} /> : null}
      </Card>
      {connected && (
        <>
          <div className="debug-grid">
            <Card
              title="會話"
              extra={<Button onClick={newSession}>建立會話</Button>}
            >
              <Load query={sessions}>
                <Table
                  size="small"
                  rowKey="id"
                  pagination={{ pageSize: 8 }}
                  dataSource={sessions.data?.items}
                  columns={[
                    {
                      title: "會話",
                      dataIndex: "id",
                      render: (id) => (
                        <Button
                          type={id === session ? "primary" : "link"}
                          onClick={() => {
                            setSession(id);
                            setAfter(0);
                          }}
                        >
                          {id.slice(0, 8)}
                        </Button>
                      ),
                    },
                    {
                      title: "服務對象",
                      dataIndex: "subject_id",
                      render: (id) =>
                        subjects.data?.items.find((s) => s.id === id)?.name ||
                        id.slice(0, 8),
                    },
                    { title: "訊息", dataIndex: "message_count" },
                  ]}
                />
                <small className="muted">顯示最近 100 個可存取會話</small>
              </Load>
            </Card>
            <Card
              title="會話訊息"
              extra={
                session && (
                  <Space>
                    <Button onClick={addMessage}>錄入訊息</Button>
                    <Button type="primary" onClick={commit}>
                      提交提取
                    </Button>
                  </Space>
                )
              }
            >
              {!session ? (
                <p className="muted">選擇或建立會話。</p>
              ) : (
                <Load query={messages}>
                  {messages.data?.items.map((m) => (
                    <div className={"message message-" + m.role} key={m.id}>
                      <small>
                        {m.role === "user" ? "用戶" : "外部 Agent"} · #
                        {m.sequence}
                      </small>
                      <p>{m.content}</p>
                    </div>
                  ))}
                  {!messages.data?.items.length && (
                    <p className="muted">尚無訊息</p>
                  )}
                  <Space>
                    <Button
                      disabled={!after}
                      onClick={() => setAfter(Math.max(0, after - 50))}
                    >
                      較早訊息
                    </Button>
                    <Button
                      disabled={(messages.data?.items.length || 0) < 50}
                      onClick={() =>
                        setAfter(messages.data!.items.at(-1)!.sequence)
                      }
                    >
                      較新訊息
                    </Button>
                  </Space>
                </Load>
              )}
            </Card>
          </div>
          <Card title="查詢提取任務" className="section-card">
            <Input.Search
              aria-label="任務 ID"
              placeholder="貼上任務 ID 查詢"
              enterButton="查詢"
              onSearch={(value) => {
                if (value.trim() === job) void jobStatus.refetch();
                else setJob(value.trim());
                setError(null);
              }}
            />
            {job && (
              <Load query={jobStatus}>
                {jobStatus.data && (
                  <div className="job-summary">
                    <Status value={jobStatus.data.state} />
                    <p>任務：{jobStatus.data.id}</p>
                    <p>
                      嘗試 {jobStatus.data.attempt} 次 ·{" "}
                      {when(jobStatus.data.updated_at)}
                    </p>
                    {jobStatus.data.error_code && (
                      <Alert
                        type="warning"
                        message={jobStatus.data.error_code}
                      />
                    )}
                    <p className="muted">追蹤：{jobStatus.data.request_id}</p>
                    {jobStatus.data.state === "failed" && (
                      <Button
                        onClick={() =>
                          forms.open({
                            title: "重試此任務？",
                            fields: [],
                            submit: () => send(`/v1/jobs/${job}/retry`),
                          })
                        }
                      >
                        重試任務
                      </Button>
                    )}
                    {jobStatus.data.state === "succeeded" && (
                      <Alert
                        type="success"
                        message="提取完成，請到記憶治理檢查候選；尚未發布為有效記憶。"
                      />
                    )}
                  </div>
                )}
              </Load>
            )}
            {error ? <Problem error={error} /> : null}
          </Card>
        </>
      )}
      {forms.modal}
    </>
  );
}
