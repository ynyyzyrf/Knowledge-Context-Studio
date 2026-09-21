import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Drawer,
  Select,
  Space,
  Table,
  Tabs,
  Timeline,
} from "antd";
import {
  Heading,
  Load,
  Problem,
  Status,
  useData,
  useForms,
  useWrite,
  when,
} from "./shared";
import type { Candidate, Entity, Items, Memory, Provenance } from "./types";
import { Pager } from "./pages";
export function Cognition() {
  const agents = useData<Items<Entity>>("/agents");
  const [agent, setAgent] = useState("");
  const subjects = useData<Items<Entity>>(`/agents/${agent}/subjects`, !!agent);
  const [subject, setSubject] = useState("");
  const [offset, setOffset] = useState(0);
  const cognition = useData<{ candidates: Candidate[]; memories: Memory[] }>(
    `/agents/${agent}/subjects/${subject}/cognition?offset=${offset}&limit=50`,
    !!agent && !!subject,
  );
  const write = useWrite();
  const forms = useForms();
  const [source, setSource] = useState<{
    type: "candidates" | "memories";
    id: string;
  } | null>(null);
  const provenance = useData<Provenance>(
    `/${source?.type}/${source?.id}/provenance`,
    !!source,
  );
  const change = (item: Memory, action: "edit" | "disable" | "delete") =>
    forms.open({
      title:
        action === "edit"
          ? "修正記憶"
          : action === "disable"
            ? "停用記憶？"
            : "刪除記憶？",
      note:
        action === "delete"
          ? "產品層立即禁止使用並清除記憶正文；引擎清理另以發布狀態追蹤。"
          : `以版本 ${item.version} 提交；其他人修改後需重新載入。`,
      danger: action !== "edit",
      fields: [
        ...(action === "edit"
          ? [
              {
                name: "content",
                label: "記憶內容",
                type: "textarea" as const,
                max: 4000,
              },
            ]
          : []),
        { name: "reason", label: "原因", type: "textarea", max: 1000 },
      ],
      values: { content: item.content },
      submit: (v) =>
        write(
          `/memories/${item.id}${action === "edit" ? "" : "/" + action}`,
          action === "edit" ? "PATCH" : "POST",
          {
            ...v,
            content: action === "edit" ? v.content : undefined,
            expected_version: item.version,
          },
        ),
    });
  return (
    <>
      <Heading
        title="記憶治理"
        note="候選先審核，有效記憶保留版本與來源；不同服務對象的記憶獨立管理。"
      />
      <div className="selection-bar">
        <Select
          aria-label="選擇外部 Agent"
          placeholder="選擇外部 Agent"
          value={agent || undefined}
          loading={agents.isPending}
          options={agents.data?.items.map((a) => ({
            value: a.id,
            label: a.name,
          }))}
          onChange={(id) => {
            setAgent(id);
            setSubject("");
            setOffset(0);
          }}
        />
        <Select
          aria-label="選擇服務對象"
          placeholder="選擇服務對象"
          value={subject || undefined}
          disabled={!agent}
          options={subjects.data?.items.map((s) => ({
            value: s.id,
            label: s.name + (s.active ? "" : "（停用）"),
          }))}
          onChange={(id) => {
            setSubject(id);
            setOffset(0);
          }}
        />
        {subject && (
          <Button onClick={() => cognition.refetch()}>重新載入</Button>
        )}
      </div>
      {agents.error ? <Problem error={agents.error} /> : null}
      {agent && subjects.error ? <Problem error={subjects.error} /> : null}
      {!subject ? (
        <Card>
          <p className="muted">選擇 Agent 與服務對象，查看候選和記憶。</p>
        </Card>
      ) : (
        <Load query={cognition}>
          <Tabs
            items={[
              {
                key: "candidates",
                label: "候選記憶",
                children: (
                  <Table
                    rowKey="id"
                    pagination={false}
                    dataSource={cognition.data?.candidates}
                    scroll={{ x: 700 }}
                    columns={[
                      {
                        title: "內容",
                        dataIndex: "content",
                        render: (t) => (
                          <div className="memory-text">{t || "正文已清除"}</div>
                        ),
                      },
                      {
                        title: "狀態",
                        dataIndex: "status",
                        render: (s) => <Status value={s} />,
                      },
                      {
                        title: "操作",
                        render: (_, c) => (
                          <Space wrap>
                            <Button
                              onClick={() =>
                                setSource({ type: "candidates", id: c.id })
                              }
                            >
                              查看來源
                            </Button>
                            {c.status === "candidate" && (
                              <>
                                <Button
                                  type="primary"
                                  onClick={() =>
                                    forms.open({
                                      title: "審核此候選？",
                                      note: "審核後進入待發布，尚不代表已可檢索。",
                                      fields: [],
                                      submit: () =>
                                        write(
                                          `/candidates/${c.id}/approve`,
                                          "POST",
                                          { expected_version: c.version },
                                        ),
                                    })
                                  }
                                >
                                  審核
                                </Button>
                                <Button
                                  onClick={() =>
                                    forms.open({
                                      title: "拒絕此候選",
                                      fields: [
                                        {
                                          name: "reason",
                                          label: "原因",
                                          type: "textarea",
                                          max: 1000,
                                        },
                                      ],
                                      submit: (v) =>
                                        write(
                                          `/candidates/${c.id}/reject`,
                                          "POST",
                                          { ...v, expected_version: c.version },
                                        ),
                                    })
                                  }
                                >
                                  拒絕
                                </Button>
                              </>
                            )}
                          </Space>
                        ),
                      },
                    ]}
                  />
                ),
              },
              {
                key: "memories",
                label: "記憶與版本",
                children: (
                  <>
                    <Alert
                      className="section-note"
                      type="info"
                      message="引擎發布尚未接通；「待發布」記憶不會被視為可檢索內容。"
                    />
                    <Table
                      rowKey="id"
                      pagination={false}
                      dataSource={cognition.data?.memories}
                      scroll={{ x: 850 }}
                      columns={[
                        {
                          title: "內容",
                          dataIndex: "content",
                          render: (t) => (
                            <div className="memory-text">
                              {t || "正文已刪除"}
                            </div>
                          ),
                        },
                        {
                          title: "版本",
                          dataIndex: "version",
                          render: (v) => `v${v}`,
                        },
                        {
                          title: "狀態",
                          dataIndex: "status",
                          render: (s) =>
                            s === "pending" ? (
                              <span className="pending">待發布</span>
                            ) : (
                              <Status value={s} />
                            ),
                        },
                        {
                          title: "引擎處理",
                          render: (_, m) => (
                            <Status value={m.publication.state} />
                          ),
                        },
                        {
                          title: "操作",
                          render: (_, m) => (
                            <Space wrap>
                              <Button
                                onClick={() =>
                                  setSource({ type: "memories", id: m.id })
                                }
                              >
                                來源／歷史
                              </Button>
                              {m.status !== "deleted" && (
                                <>
                                  <Button onClick={() => change(m, "edit")}>
                                    修正
                                  </Button>
                                  <Button
                                    disabled={m.status === "disabled"}
                                    onClick={() => change(m, "disable")}
                                  >
                                    停用
                                  </Button>
                                  <Button
                                    danger
                                    onClick={() => change(m, "delete")}
                                  >
                                    刪除
                                  </Button>
                                </>
                              )}
                            </Space>
                          ),
                        },
                      ]}
                    />
                  </>
                ),
              },
            ]}
          />
          <Pager
            offset={offset}
            count={Math.max(
              cognition.data?.candidates.length || 0,
              cognition.data?.memories.length || 0,
            )}
            setOffset={setOffset}
          />
        </Load>
      )}
      <Drawer
        open={!!source}
        width={680}
        title="記憶來源與版本"
        onClose={() => setSource(null)}
      >
        {source && (
          <Load query={provenance}>
            <h3>來源訊息</h3>
            {provenance.data?.messages.length ? (
              provenance.data.messages.map((m) => (
                <Card
                  key={m.id}
                  size="small"
                  className="source-card"
                  title={m.role === "user" ? "用戶訊息" : "外部 Agent 訊息"}
                >
                  <div className="memory-text">{m.content}</div>
                  <small className="muted">來源：{m.id}</small>
                </Card>
              ))
            ) : (
              <p className="muted">沒有可顯示的來源正文。</p>
            )}
            {provenance.data?.revisions && (
              <>
                <h3>版本歷史</h3>
                <Timeline
                  items={provenance.data.revisions.map((r) => ({
                    children: (
                      <>
                        <strong>v{r.version}</strong>{" "}
                        <Status value={r.status} />
                        <p>{r.content || "正文已刪除"}</p>
                        <p className="muted">
                          {r.reason} · {when(r.created_at)}
                        </p>
                      </>
                    ),
                  }))}
                />
              </>
            )}
          </Load>
        )}
      </Drawer>
      {forms.modal}
    </>
  );
}
