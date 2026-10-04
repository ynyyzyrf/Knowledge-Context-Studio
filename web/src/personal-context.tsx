import { useState } from "react";
import {
  Alert,
  Button,
  Drawer,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
} from "antd";
import { Load, Problem, useData, useWrite, when } from "./shared";

type Kind = "memories" | "sessions" | "skills" | "peers";
const names: Record<Kind, string> = {
  memories: "長期記憶",
  sessions: "會話紀錄",
  skills: "Skill",
  peers: "對象上下文",
};
const statuses: Record<string, string> = {
  pending: "待審核",
  active: "已啟用",
  disabled: "已停用",
};
type Entry = {
  id: string;
  title: string;
  content: string;
  status: string;
  version: number;
  created_by: string;
  created_at: number;
  updated_at: number;
  source_message_ids: string[];
  indexing?: { state: string; error_code: string | null };
  revisions?: {
    version: number;
    title: string;
    content: string;
    status: string;
    created_at: number;
  }[];
};
type Draft = {
  id?: string;
  title: string;
  content: string;
  status: string;
  version?: number;
  source_message_ids?: string[];
  kind?: Kind;
  external_id: string;
};
const fresh = (): Draft => ({
  title: "",
  content: "",
  status: "pending",
  external_id: crypto.randomUUID(),
});

export function PersonalContext({
  spaceId,
  folder,
}: {
  spaceId: string;
  folder: string;
}) {
  const kind = folder as Kind;
  const base = `/spaces/${spaceId}/user/default/${kind}`;
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string>();
  const [draft, setDraft] = useState<Draft>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const write = useWrite();
  const data = useData<{ items: Entry[]; total: number }>(
    `${base}/entries?offset=${(page - 1) * 10}&limit=10&q=${encodeURIComponent(query)}`,
  );
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(undefined);
    try {
      await action();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const save = () =>
    run(async () => {
      if (!draft) return;
      const target = `/spaces/${spaceId}/user/default/${draft.kind || kind}/entries`;
      if (draft.id)
        await write(`${target}/${draft.id}`, "PUT", {
          title: draft.title,
          content: draft.content,
          status: draft.status,
          version: draft.version,
        });
      else
        await write(target, "POST", {
          title: draft.title,
          content: draft.content,
          external_id: draft.external_id,
          source_message_ids: draft.source_message_ids || [],
        });
      setDraft(undefined);
    });
  return (
    <div className="personal-context">
      <h2>{names[kind]}</h2>
      <p className="muted">
        此空間內屬於你的私人上下文。
        {kind === "sessions"
          ? "保存對話及任務訊息，可將重要訊息提交為候選記憶。"
          : kind === "skills"
            ? "保存 Skill 內容與版本；審核啟用後供已授權 Agent 讀取，平台不執行 Skill。"
            : "新增內容先待審核，啟用後才提供給已授權 Agent。"}
      </p>
      {error ? <Problem error={error} /> : null}
      <Tabs
        items={[
          {
            key: "entries",
            label: "資料",
            children: (
              <>
                <div className="personal-toolbar">
                  <Input.Search
                    allowClear
                    aria-label="搜尋個人上下文"
                    placeholder="搜尋標題與說明（關鍵字）"
                    onSearch={(value) => {
                      setQuery(value);
                      setPage(1);
                      setSelected(undefined);
                    }}
                  />
                  <Button type="primary" onClick={() => setDraft(fresh())}>
                    新增{names[kind]}
                  </Button>
                  <Button onClick={() => void data.refetch()}>重新載入</Button>
                </div>
                <Load query={data}>
                  <Table
                    rowKey="id"
                    dataSource={data.data?.items}
                    scroll={{ x: 560 }}
                    pagination={{
                      current: page,
                      pageSize: 10,
                      total: data.data?.total || 0,
                      showSizeChanger: false,
                      position: ["bottomRight"],
                      showTotal: (n) => `共 ${n} 筆`,
                      onChange: setPage,
                    }}
                    columns={[
                      {
                        title: "名稱",
                        dataIndex: "title",
                        render: (value: string, row: Entry) => (
                          <Button
                            type="link"
                            className="personal-title"
                            onClick={() => setSelected(row.id)}
                          >
                            {value}
                          </Button>
                        ),
                      },
                      {
                        title: "狀態",
                        dataIndex: "status",
                        width: 100,
                        render: (value: string) => (
                          <Tag
                            color={
                              value === "active"
                                ? "green"
                                : value === "pending"
                                  ? "gold"
                                  : undefined
                            }
                          >
                            {statuses[value]}
                          </Tag>
                        ),
                      },
                      { title: "版本", dataIndex: "version", width: 65 },
                      {
                        title: "更新時間",
                        dataIndex: "updated_at",
                        width: 180,
                        render: when,
                      },
                    ]}
                  />
                </Load>
              </>
            ),
          },
          {
            key: "access",
            label: "Agent 授權",
            children: <NamespaceAccess base={base} />,
          },
        ]}
      />
      <Drawer
        title={names[kind]}
        open={!!selected}
        width={700}
        onClose={() => setSelected(undefined)}
        destroyOnClose
      >
        {selected && (
          <EntryReader
            key={selected}
            base={base}
            kind={kind}
            id={selected}
            busy={busy}
            onEdit={(row) =>
              setDraft({ ...row, external_id: crypto.randomUUID() })
            }
            onCandidate={(id, content) => {
              setDraft({
                ...fresh(),
                kind: "memories",
                title: content.slice(0, 80),
                content,
                source_message_ids: [id],
              });
            }}
            onDelete={(row) =>
              run(async () => {
                await write(`${base}/entries/${row.id}/delete`, "POST", {
                  version: row.version,
                });
                setSelected(undefined);
                if (data.data?.items.length === 1 && page > 1)
                  setPage(page - 1);
              })
            }
          />
        )}
      </Drawer>
      <Modal
        zIndex={1200}
        title={draft?.id ? "編輯與審核" : `新增${names[draft?.kind || kind]}`}
        open={!!draft}
        onCancel={() => {
          if (!busy) setDraft(undefined);
        }}
        onOk={save}
        confirmLoading={busy}
        okButtonProps={{
          disabled:
            !draft?.title.trim() ||
            ((draft?.kind || kind) !== "sessions" && !draft?.content.trim()),
        }}
        okText="保存"
        cancelText="取消"
        width={720}
      >
        {error ? <Problem error={error} /> : null}
        {draft && (
          <div className="personal-editor">
            <label>
              名稱
              <Input
                value={draft.title}
                maxLength={200}
                onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              />
            </label>
            <label>
              內容
              <Input.TextArea
                value={draft.content}
                maxLength={40000}
                rows={12}
                onChange={(e) =>
                  setDraft({ ...draft, content: e.target.value })
                }
              />
            </label>
            {draft.id ? (
              <label>
                狀態
                <Select
                  aria-label="上下文狀態"
                  value={draft.status}
                  onChange={(status) => setDraft({ ...draft, status })}
                  options={Object.entries(statuses).map(([value, label]) => ({
                    value,
                    label,
                  }))}
                />
              </label>
            ) : (
              <p className="muted">
                {(draft.kind || kind) === "sessions"
                  ? "建立後可新增訊息。"
                  : "保存為待審核；閱讀並啟用後，Agent 才能取得內容。"}
              </p>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}

function EntryReader({
  base,
  kind,
  id,
  onEdit,
  onDelete,
  onCandidate,
  busy,
}: {
  base: string;
  kind: Kind;
  id: string;
  onEdit: (row: Entry) => void;
  onDelete: (row: Entry) => void;
  onCandidate: (id: string, content: string) => void;
  busy: boolean;
}) {
  const data = useData<Entry>(`${base}/entries/${id}`);
  const write = useWrite();
  const [indexBusy, setIndexBusy] = useState(false);
  const [indexError, setIndexError] = useState<unknown>();
  const retryIndex = async () => {
    if (!data.data) return;
    setIndexBusy(true);
    setIndexError(undefined);
    try {
      await write(`${base}/entries/${id}/reindex`, "POST", {
        version: data.data.version,
      });
    } catch (error) {
      setIndexError(error);
    } finally {
      setIndexBusy(false);
    }
  };
  return (
    <Load query={data}>
      {data.data && (
        <>
          <h3>{data.data.title}</h3>
          {indexError ? <Problem error={indexError} /> : null}
          {kind !== "sessions" &&
            data.data.status === "active" &&
            data.data.indexing && (
              <Space wrap style={{ marginBottom: 12 }}>
                <Tag
                  color={
                    data.data.indexing.state === "ready" ? "green" : "gold"
                  }
                >
                  {{
                    ready: "語意索引已就緒",
                    pending: "等待語意索引",
                    running: "語意索引中",
                    retry: "語意索引稍後重試",
                    failed: "語意索引失敗",
                    inactive: "語意索引未啟用",
                  }[data.data.indexing.state] || "等待語意索引"}
                </Tag>
                {data.data.indexing.state !== "ready" && (
                  <span className="muted">目前仍可用關鍵字檢索。</span>
                )}
                {data.data.indexing.state === "failed" && (
                  <Button loading={indexBusy} onClick={() => void retryIndex()}>
                    重試索引
                  </Button>
                )}
                <Button onClick={() => void data.refetch()}>刷新狀態</Button>
              </Space>
            )}
          <Space wrap>
            <Tag>{statuses[data.data.status]}</Tag>
            <span>v{data.data.version}</span>
            <Button onClick={() => onEdit(data.data!)}>編輯／審核</Button>
            <Popconfirm
              title="刪除此資料及所有版本正文？"
              onConfirm={() => onDelete(data.data!)}
              okText="刪除"
              cancelText="取消"
            >
              <Button danger disabled={busy}>
                刪除
              </Button>
            </Popconfirm>
          </Space>
          <Tabs
            items={[
              {
                key: "content",
                label: "完整內容",
                children: (
                  <div className="document-fulltext">
                    {data.data.content || "尚無會話說明。"}
                  </div>
                ),
              },
              ...(kind === "sessions"
                ? [
                    {
                      key: "messages",
                      label: "會話訊息",
                      children: (
                        <SessionMessages
                          base={base}
                          id={id}
                          active={data.data.status === "active"}
                          onCandidate={onCandidate}
                        />
                      ),
                    },
                  ]
                : []),
              {
                key: "versions",
                label: "版本紀錄",
                children: (
                  <>
                    <p className="muted">顯示最近 50 個版本。</p>
                    {data.data.revisions?.map((r) => (
                      <section key={r.version} className="document-text-page">
                        <h4>
                          v{r.version} · {statuses[r.status]} ·{" "}
                          {when(r.created_at)}
                        </h4>
                        <strong>{r.title}</strong>
                        <p className="document-fulltext">{r.content}</p>
                      </section>
                    ))}
                  </>
                ),
              },
              ...(kind === "memories"
                ? [
                    {
                      key: "sources",
                      label: "來源訊息",
                      children: <Sources base={base} id={id} />,
                    },
                  ]
                : []),
            ]}
          />
        </>
      )}
    </Load>
  );
}

function Sources({ base, id }: { base: string; id: string }) {
  const data = useData<{
    items: { id: string; session_title: string; content: string }[];
    unavailable_count: number;
  }>(`${base}/entries/${id}/sources`);
  return (
    <Load query={data}>
      {data.data?.items.map((m) => (
        <section key={m.id}>
          <h4>{m.session_title}</h4>
          <p className="document-fulltext">{m.content}</p>
        </section>
      ))}
      {!data.data?.items.length && (
        <p className="muted">
          尚無可讀來源訊息；手動建立的記憶可沒有會話來源。
        </p>
      )}
      {!!data.data?.unavailable_count && (
        <Alert
          type="info"
          message={`${data.data.unavailable_count} 則來源已不可用。`}
        />
      )}
    </Load>
  );
}

function SessionMessages({
  base,
  id,
  active,
  onCandidate,
}: {
  base: string;
  id: string;
  active: boolean;
  onCandidate: (id: string, content: string) => void;
}) {
  const [page, setPage] = useState(0),
    [text, setText] = useState(""),
    [role, setRole] = useState("user"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>();
  const [messageKey, setMessageKey] = useState(() => crypto.randomUUID());
  const write = useWrite();
  const data = useData<{
    items: { id: string; role: string; content: string; sequence: number }[];
    has_more: boolean;
  }>(`${base}/entries/${id}/messages?offset=${page * 20}&limit=20`);
  const send = async () => {
    setBusy(true);
    setError(undefined);
    try {
      await write(`${base}/entries/${id}/messages`, "POST", {
        external_id: messageKey,
        role,
        content: text,
      });
      setText("");
      setMessageKey(crypto.randomUUID());
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Load query={data}>
        {data.data?.items.map((m) => (
          <section key={m.id} className="document-text-page">
            <h4>
              #{m.sequence} · {m.role}
            </h4>
            <p className="document-fulltext">{m.content}</p>
            <Button onClick={() => onCandidate(m.id, m.content)}>
              提交為候選記憶
            </Button>
          </section>
        ))}
        {!data.data?.items.length && <p className="muted">尚無訊息。</p>}
        <Space>
          <Button disabled={!page} onClick={() => setPage(page - 1)}>
            上一頁
          </Button>
          <span>第 {page + 1} 頁</span>
          <Button
            disabled={!data.data?.has_more}
            onClick={() => setPage(page + 1)}
          >
            下一頁
          </Button>
        </Space>
      </Load>
      {error ? <Problem error={error} /> : null}
      {active && (
        <div className="personal-editor">
          <Select
            aria-label="訊息角色"
            value={role}
            disabled={busy}
            onChange={(value) => {
              setRole(value);
              setMessageKey(crypto.randomUUID());
            }}
            options={["user", "assistant", "tool", "system"].map((value) => ({
              value,
              label: value,
            }))}
          />
          <Input.TextArea
            aria-label="新增訊息內容"
            disabled={busy}
            value={text}
            rows={5}
            maxLength={16000}
            onChange={(e) => {
              setText(e.target.value);
              setMessageKey(crypto.randomUUID());
            }}
          />
          <Button
            type="primary"
            loading={busy}
            disabled={!text.trim()}
            onClick={send}
          >
            新增訊息
          </Button>
        </div>
      )}
    </>
  );
}

function NamespaceAccess({ base }: { base: string }) {
  const data = useData<{
    items: {
      agent_id: string;
      name: string;
      can_read: boolean;
      can_write: boolean;
      auto_store: boolean;
    }[];
  }>(`${base}/agent-access`);
  const write = useWrite();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>();
  return (
    <>
      <p className="muted">
        分別授予此目錄的讀取及提交權限；只適用於綁定你的 Token，且 Agent
        必須同時具有此空間權限。記憶可另行開啟自動存儲，完整保存提交內容；不會自動收集對話。
      </p>
      {error ? <Problem error={error} /> : null}
      <Load query={data}>
        <Table
          rowKey="agent_id"
          dataSource={data.data?.items}
          pagination={false}
          columns={[
            { title: "Agent", dataIndex: "name" },
            ...(
              [
                "can_read",
                "can_write",
                ...(base.endsWith("/memories") ? ["auto_store" as const] : []),
              ] as const
            ).map((key) => ({
              title:
                key === "can_read"
                  ? "讀取"
                  : key === "auto_store"
                    ? "自動存儲"
                    : "提交",
              key,
              render: (
                _: unknown,
                a: {
                  agent_id: string;
                  name: string;
                  can_read: boolean;
                  can_write: boolean;
                  auto_store: boolean;
                },
              ) => (
                <Switch
                  aria-label={`${key === "can_read" ? "讀取" : key === "auto_store" ? "自動存儲" : "提交"} ${a.name}`}
                  checked={a[key]}
                  disabled={busy || (key === "auto_store" && !a.can_write)}
                  onChange={async (value) => {
                    setBusy(true);
                    setError(undefined);
                    try {
                      await write(`${base}/agent-access/${a.agent_id}`, "PUT", {
                        can_read: a.can_read,
                        can_write: a.can_write,
                        auto_store:
                          key === "can_write" && !value ? false : a.auto_store,
                        [key]: value,
                      });
                    } catch (e) {
                      setError(e);
                    } finally {
                      setBusy(false);
                    }
                  }}
                />
              ),
            })),
          ]}
        />
      </Load>
    </>
  );
}
