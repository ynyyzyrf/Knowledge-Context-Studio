import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Button,
  Card,
  Drawer,
  Modal,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import {
  PlusOutlined,
  ArrowRightOutlined,
  ReloadOutlined,
  KeyOutlined,
} from "@ant-design/icons";
import {
  Blank,
  Heading,
  ID,
  Load,
  Status,
  useData,
  useForms,
  useWorkspace,
  useWrite,
  when,
  type Field,
} from "./shared";
import type {
  Audit,
  Credential,
  Entity,
  Issued,
  Items,
  Job,
  Person,
  Space as SpaceType,
} from "./types";
const nameField: Field = { name: "name", label: "名稱", max: 160 };
const roleOptions = [
  { value: "viewer", label: "檢視者" },
  { value: "editor", label: "編輯者" },
  { value: "tenant_admin", label: "團隊管理員" },
];
const activeField: Field = {
  name: "active",
  label: "授權狀態",
  type: "select",
  options: [
    { value: "yes", label: "授予存取" },
    { value: "no", label: "撤銷存取" },
  ],
};

export function Spaces() {
  const { tenant } = useWorkspace();
  const admin = tenant.role === "tenant_admin";
  const data = useData<Items<SpaceType>>("/spaces");
  const write = useWrite();
  const forms = useForms();
  const [selected, setSelected] = useState<SpaceType | null>(null);
  return (
    <>
      <Heading
        title="知識空間"
        note="依專案組織知識，清楚界定人員與外部 Agent 的存取範圍。"
        extra={
          admin && (
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() =>
                forms.open({
                  title: "建立知識空間",
                  fields: [nameField],
                  submit: (v) => write("/spaces", "POST", v),
                })
              }
            >
              建立空間
            </Button>
          )
        }
      />
      <Alert
        className="section-note"
        type="info"
        showIcon
        message="目前可管理空間與授權；文件匯入與檢索尚未接通。"
      />
      <Load query={data}>
        {data.data?.items.length ? (
          <div className="space-grid">
            {data.data.items.map((s) => (
              <Card
                key={s.id}
                className="space-card"
                title={s.name}
                extra={<Status value={s.sync_state} />}
              >
                <div className="space-mark">知</div>
                <p className="muted">
                  {s.sync_state === "ready" ? "引擎同步完成" : "待完成引擎同步"}
                </p>
                <div className="card-bottom">
                  <ID value={s.id} />
                  <Button
                    type="link"
                    icon={<ArrowRightOutlined />}
                    onClick={() => setSelected(s)}
                  >
                    {admin ? "管理授權" : "查看空間"}
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        ) : (
          <Blank text="尚無可存取的知識空間" />
        )}
      </Load>
      {selected && (
        <SpaceDetail
          space={selected}
          close={() => setSelected(null)}
          admin={admin}
        />
      )}
      {forms.modal}
    </>
  );
}
function SpaceDetail({
  space,
  close,
  admin,
}: {
  space: SpaceType;
  close: () => void;
  admin: boolean;
}) {
  const grants = useData<{
    people: { person_id: string; level: string; active: boolean }[];
    agents: { agent_id: string; active: boolean }[];
  }>(`/spaces/${space.id}/grants`, admin);
  const people = useData<Items<Person>>("/members", admin);
  const agents = useData<Items<Entity>>("/agents", admin);
  const write = useWrite();
  const forms = useForms();
  return (
    <Drawer open title={space.name} width={660} onClose={close}>
      <Space direction="vertical" style={{ width: "100%" }} size="large">
        <Status value={space.sync_state} />
        <Typography.Paragraph copyable>{space.id}</Typography.Paragraph>
        {!admin ? (
          <Alert
            type="info"
            message="你可以查看此空間；內容匯入與檢索功能尚未接通。"
          />
        ) : (
          <Load query={grants}>
            <Tabs
              items={[
                {
                  key: "people",
                  label: "人員授權",
                  children: (
                    <>
                      <Button
                        onClick={() =>
                          forms.open({
                            title: "設定人員授權",
                            fields: [
                              {
                                name: "person_id",
                                label: "團隊成員",
                                type: "select",
                                options: people.data?.items
                                  .filter((x) => x.active)
                                  .map((x) => ({
                                    value: x.person_id,
                                    label: x.email,
                                  })),
                              },
                              {
                                name: "level",
                                label: "空間權限",
                                type: "select",
                                options: roleOptions.slice(0, 2),
                              },
                              activeField,
                            ],
                            values: { level: "viewer", active: "yes" },
                            submit: (v) =>
                              write(
                                `/spaces/${space.id}/people/${v.person_id}`,
                                "PUT",
                                { level: v.level, active: v.active === "yes" },
                              ),
                          })
                        }
                      >
                        設定授權
                      </Button>
                      <Table
                        rowKey="person_id"
                        pagination={false}
                        dataSource={grants.data?.people}
                        columns={[
                          {
                            title: "成員",
                            dataIndex: "person_id",
                            render: (id) =>
                              people.data?.items.find((p) => p.person_id === id)
                                ?.email || id,
                          },
                          {
                            title: "權限",
                            dataIndex: "level",
                            render: (v) => <Status value={v} />,
                          },
                          {
                            title: "狀態",
                            dataIndex: "active",
                            render: (v) => (
                              <Status value={v ? "active" : "disabled"} />
                            ),
                          },
                        ]}
                      />
                    </>
                  ),
                },
                {
                  key: "agents",
                  label: "Agent 授權",
                  children: (
                    <>
                      <Button
                        onClick={() =>
                          forms.open({
                            title: "設定外部 Agent 授權",
                            fields: [
                              {
                                name: "agent_id",
                                label: "Agent",
                                type: "select",
                                options: agents.data?.items.map((a) => ({
                                  value: a.id,
                                  label: a.name,
                                })),
                              },
                              activeField,
                            ],
                            values: { active: "yes" },
                            submit: (v) =>
                              write(
                                `/spaces/${space.id}/agents/${v.agent_id}`,
                                "PUT",
                                { active: v.active === "yes" },
                              ),
                          })
                        }
                      >
                        設定授權
                      </Button>
                      <Table
                        rowKey="agent_id"
                        pagination={false}
                        dataSource={grants.data?.agents}
                        columns={[
                          {
                            title: "Agent",
                            dataIndex: "agent_id",
                            render: (id) =>
                              agents.data?.items.find((a) => a.id === id)
                                ?.name || id,
                          },
                          {
                            title: "狀態",
                            dataIndex: "active",
                            render: (v) => (
                              <Status value={v ? "active" : "disabled"} />
                            ),
                          },
                        ]}
                      />
                    </>
                  ),
                },
              ]}
            />
          </Load>
        )}
      </Space>
      {forms.modal}
    </Drawer>
  );
}

export function Agents() {
  const data = useData<Items<Entity>>("/agents");
  const write = useWrite();
  const forms = useForms();
  const [selected, setSelected] = useState<Entity | null>(null);
  return (
    <>
      <Heading
        title="外部 Agent 接入"
        note="登記外部服務身份與授權。Agent 在你的外部系統執行，平台不託管 Agent。"
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() =>
              forms.open({
                title: "登記外部 Agent",
                note: "建立服務身份，不會建立或啟動 Agent 執行器。",
                fields: [nameField],
                submit: (v) => write("/agents", "POST", v),
              })
            }
          >
            登記 Agent
          </Button>
        }
      />
      <Load query={data}>
        <Table
          rowKey="id"
          dataSource={data.data?.items}
          locale={{
            emptyText: <Blank text="登記第一個外部 Agent，開始管理接入權限" />,
          }}
          columns={[
            {
              title: "名稱",
              dataIndex: "name",
              render: (name, a) => (
                <Button type="link" onClick={() => setSelected(a)}>
                  {name}
                </Button>
              ),
            },
            {
              title: "接入身份",
              dataIndex: "id",
              render: (id) => <ID value={id} />,
            },
            {
              title: "狀態",
              dataIndex: "active",
              render: (v) => <Status value={v ? "active" : "disabled"} />,
            },
            {
              title: "操作",
              render: (_, a) => (
                <Space>
                  <Button onClick={() => setSelected(a)}>管理接入</Button>
                  <Button
                    danger={a.active}
                    onClick={() =>
                      forms.open({
                        title: a.active ? "停用此 Agent？" : "啟用此 Agent？",
                        note: "停用後其憑證將無法呼叫 API，尚未完成的提取也會重新檢查權限。",
                        fields: [],
                        danger: a.active,
                        submit: () =>
                          write(`/agents/${a.id}`, "PATCH", {
                            active: !a.active,
                          }),
                      })
                    }
                  >
                    {a.active ? "停用" : "啟用"}
                  </Button>
                </Space>
              ),
            },
          ]}
          scroll={{ x: 700 }}
        />
      </Load>
      {selected && (
        <AgentDetail
          agent={data.data?.items.find((a) => a.id === selected.id) || selected}
          close={() => setSelected(null)}
        />
      )}
      {forms.modal}
    </>
  );
}
function AgentDetail({ agent, close }: { agent: Entity; close: () => void }) {
  const subjects = useData<Items<Entity>>(`/agents/${agent.id}/subjects`);
  const credentials = useData<Items<Credential>>(
    `/agents/${agent.id}/credentials`,
  );
  const base = `/agents/${agent.id}`;
  const write = useWrite();
  const forms = useForms();
  const [issued, setIssued] = useState<Issued | null>(null);
  const { setToken } = useWorkspace();
  const navigate = useNavigate();
  return (
    <Drawer open title={agent.name} width={780} onClose={close}>
      <Alert
        type="info"
        showIcon
        message="服務對象是記憶隔離範圍，不是平台登入帳號。"
      />
      <Tabs
        items={[
          {
            key: "subjects",
            label: "服務對象",
            children: (
              <>
                <Button
                  icon={<PlusOutlined />}
                  onClick={() =>
                    forms.open({
                      title: "新增服務對象",
                      fields: [nameField],
                      submit: (v) => write(base + "/subjects", "POST", v),
                    })
                  }
                >
                  新增服務對象
                </Button>
                <Load query={subjects}>
                  <Table
                    rowKey="id"
                    dataSource={subjects.data?.items}
                    columns={[
                      { title: "名稱", dataIndex: "name" },
                      {
                        title: "ID",
                        dataIndex: "id",
                        render: (id) => <ID value={id} />,
                      },
                      {
                        title: "狀態",
                        dataIndex: "active",
                        render: (v) => (
                          <Status value={v ? "active" : "disabled"} />
                        ),
                      },
                      {
                        title: "操作",
                        render: (_, s) => (
                          <Button
                            danger={s.active}
                            onClick={() =>
                              forms.open({
                                title: s.active
                                  ? "停用服務對象？"
                                  : "啟用服務對象？",
                                fields: [],
                                danger: s.active,
                                submit: () =>
                                  write(base + `/subjects/${s.id}`, "PATCH", {
                                    active: !s.active,
                                  }),
                              })
                            }
                          >
                            {s.active ? "停用" : "啟用"}
                          </Button>
                        ),
                      },
                    ]}
                  />
                </Load>
              </>
            ),
          },
          {
            key: "credentials",
            label: "接入憑證",
            children: (
              <>
                <Button
                  icon={<KeyOutlined />}
                  disabled={!agent.active}
                  onClick={() =>
                    forms.open({
                      title: "簽發接入憑證",
                      note: "只授權所選服務對象。原始憑證僅顯示一次。",
                      fields: [
                        {
                          name: "subject_ids",
                          label: "服務對象範圍",
                          type: "multi",
                          options: subjects.data?.items
                            .filter((s) => s.active)
                            .map((s) => ({ label: s.name, value: s.id })),
                        },
                        {
                          name: "expires_in_days",
                          label: "有效天數",
                          type: "number",
                          min: 1,
                          max: 365,
                        },
                      ],
                      values: { expires_in_days: 30 },
                      submit: async (v) =>
                        setIssued(
                          await write<Issued>(base + "/credentials", "POST", v),
                        ),
                    })
                  }
                >
                  簽發憑證
                </Button>
                <Load query={credentials}>
                  <Table
                    rowKey="id"
                    dataSource={credentials.data?.items}
                    scroll={{ x: 600 }}
                    columns={[
                      {
                        title: "憑證",
                        dataIndex: "id",
                        render: (id) => <ID value={id} />,
                      },
                      {
                        title: "有效期限",
                        dataIndex: "expires_at",
                        render: when,
                      },
                      {
                        title: "授權對象",
                        dataIndex: "subject_ids",
                        render: (ids) =>
                          (ids || [])
                            .map(
                              (id: string) =>
                                subjects.data?.items.find((s) => s.id === id)
                                  ?.name || id,
                            )
                            .join("、"),
                      },
                      {
                        title: "狀態",
                        render: (_, c) => (
                          <Tag>
                            {c.revoked_at
                              ? "已撤銷"
                              : c.expires_at < Date.now() / 1000
                                ? "已過期"
                                : "有效"}
                          </Tag>
                        ),
                      },
                      {
                        title: "操作",
                        render: (_, c) => (
                          <Space>
                            <Button
                              disabled={
                                !!c.revoked_at ||
                                c.expires_at < Date.now() / 1000
                              }
                              onClick={() =>
                                forms.open({
                                  title: "輪替接入憑證？",
                                  note: "舊憑證立即失效，新憑證沿用原到期日與授權範圍。",
                                  fields: [],
                                  submit: async () =>
                                    setIssued(
                                      await write<Issued>(
                                        base + `/credentials/${c.id}/rotate`,
                                        "POST",
                                        {},
                                      ),
                                    ),
                                })
                              }
                            >
                              輪替
                            </Button>
                            <Button
                              danger
                              disabled={!!c.revoked_at}
                              onClick={() =>
                                forms.open({
                                  title: "撤銷此憑證？",
                                  fields: [],
                                  danger: true,
                                  submit: () =>
                                    write(
                                      base + `/credentials/${c.id}`,
                                      "DELETE",
                                    ),
                                })
                              }
                            >
                              撤銷
                            </Button>
                          </Space>
                        ),
                      },
                    ]}
                  />
                </Load>
              </>
            ),
          },
        ]}
      />
      {forms.modal}
      <Modal
        open={!!issued}
        title="請保存你的接入憑證"
        onCancel={() => setIssued(null)}
        footer={
          <Space>
            <Button onClick={() => setIssued(null)}>已保存，關閉</Button>
            <Button
              type="primary"
              onClick={() => {
                setToken(issued!.token);
                setIssued(null);
                close();
                navigate("/developer");
              }}
            >
              用於 API 接入測試
            </Button>
          </Space>
        }
      >
        <Alert
          type="warning"
          message="原始憑證僅顯示這一次，關閉後無法再次查看。"
        />
        <Typography.Paragraph
          className="secret"
          copyable={{ text: issued?.token }}
        >
          {issued?.token}
        </Typography.Paragraph>
        <p>到期：{issued ? when(issued.expires_at) : ""}</p>
      </Modal>
    </Drawer>
  );
}

export function Members() {
  const { tenant } = useWorkspace();
  const admin = tenant.role === "tenant_admin";
  const data = useData<Items<Person>>("/members");
  const write = useWrite();
  const forms = useForms();
  return (
    <>
      <Heading
        title="團隊成員"
        note="成員角色決定管理權限；知識空間仍需單獨授權。"
        extra={
          admin && (
            <Space>
              <Button
                onClick={() =>
                  forms.open({
                    title: "加入既有帳號",
                    fields: [
                      { name: "email", label: "帳號信箱" },
                      {
                        name: "role",
                        label: "團隊角色",
                        type: "select",
                        options: roleOptions,
                      },
                    ],
                    values: { role: "viewer" },
                    submit: (v) => write("/members/existing", "POST", v),
                  })
                }
              >
                加入既有帳號
              </Button>
              <Button
                type="primary"
                onClick={() =>
                  forms.open({
                    title: "新增團隊帳號",
                    fields: [
                      { name: "email", label: "帳號信箱" },
                      {
                        name: "password",
                        label: "初始密碼（至少 16 字元）",
                        type: "password",
                        max: 256,
                      },
                      {
                        name: "role",
                        label: "團隊角色",
                        type: "select",
                        options: roleOptions,
                      },
                    ],
                    values: { role: "viewer" },
                    submit: (v) => write("/members", "POST", v),
                  })
                }
              >
                新增成員
              </Button>
            </Space>
          )
        }
      />
      <Load query={data}>
        <Table
          rowKey="person_id"
          dataSource={data.data?.items}
          columns={[
            { title: "電子郵件", dataIndex: "email" },
            {
              title: "角色",
              dataIndex: "role",
              render: (v) => <Status value={v} />,
            },
            {
              title: "狀態",
              dataIndex: "active",
              render: (v) => <Status value={v ? "active" : "disabled"} />,
            },
            ...(admin
              ? [
                  {
                    title: "操作",
                    render: (_: unknown, p: Person) => (
                      <Button
                        danger={p.active}
                        onClick={() =>
                          forms.open({
                            title: p.active ? "停用此成員？" : "啟用此成員？",
                            fields: [],
                            danger: p.active,
                            submit: () =>
                              write(`/members/${p.person_id}`, "PATCH", {
                                active: !p.active,
                              }),
                          })
                        }
                      >
                        {p.active ? "停用" : "啟用"}
                      </Button>
                    ),
                  },
                ]
              : []),
          ]}
        />
      </Load>
      {forms.modal}
    </>
  );
}

export function Jobs() {
  const [offset, setOffset] = useState(0);
  const [poll, setPoll] = useState(true);
  const data = useData<Items<Job>>(
    `/jobs?offset=${offset}&limit=50`,
    true,
    (result) =>
      poll &&
      !!result?.items.some((j) =>
        ["pending", "running", "retry"].includes(j.state),
      ),
  );
  const [selected, setSelected] = useState<Job | null>(null);
  const items = data.data?.items;
  const detail = items?.find((j) => j.id === selected?.id) || selected;
  const running = items?.some((j) =>
    ["pending", "running", "retry"].includes(j.state),
  );
  return (
    <>
      <Heading
        title="任務中心"
        note="追蹤會話提取的真實處理狀態。任務完成後，記憶仍需人工審核。"
        extra={
          <Space>
            <Button onClick={() => setPoll(!poll)}>
              {poll ? "暫停更新" : "自動更新"}
            </Button>
            <Button icon={<ReloadOutlined />} onClick={() => data.refetch()}>
              重新整理
            </Button>
          </Space>
        }
      />
      {poll && (
        <p className="muted">
          {running
            ? "有任務處理中，每 3 秒更新目前頁面"
            : "目前頁面無進行中任務，自動更新已暫停；可手動重新整理"}
        </p>
      )}
      <Load query={data}>
        <Table
          rowKey="id"
          pagination={false}
          dataSource={items}
          scroll={{ x: 750 }}
          columns={[
            {
              title: "任務",
              dataIndex: "id",
              render: (id, j) => (
                <Button type="link" onClick={() => setSelected(j)}>
                  {id.slice(0, 8)}
                </Button>
              ),
            },
            {
              title: "狀態",
              dataIndex: "state",
              render: (v) => <Status value={v} />,
            },
            { title: "嘗試次數", dataIndex: "attempt" },
            { title: "更新時間", dataIndex: "updated_at", render: when },
            { title: "原因", dataIndex: "error_code", render: (v) => v || "—" },
          ]}
        />
        <Pager
          offset={offset}
          count={items?.length || 0}
          setOffset={setOffset}
        />
      </Load>
      <Drawer
        open={!!selected}
        title="任務詳情"
        onClose={() => setSelected(null)}
      >
        {detail && (
          <>
            <Status value={detail.state} />
            <p>任務 ID：{detail.id}</p>
            <p>會話 ID：{detail.session_id}</p>
            <p>服務對象：{detail.subject_id}</p>
            <p>追蹤編號：{detail.request_id}</p>
            <p>
              輸入／輸出 tokens：{detail.input_tokens ?? "未回報"}／
              {detail.output_tokens ?? "未回報"}
            </p>
            <Alert
              type="info"
              message="重試需要對應 Agent 的有效憑證，請在 API 接入測試中執行。"
            />
          </>
        )}
      </Drawer>
    </>
  );
}
export function Pager({
  offset,
  count,
  setOffset,
}: {
  offset: number;
  count: number;
  setOffset: (n: number) => void;
}) {
  return (
    <div className="pager">
      <span>
        目前第 {offset / 50 + 1} 頁 · 載入 {count} 筆
      </span>
      <Space>
        <Button
          disabled={!offset}
          onClick={() => setOffset(Math.max(0, offset - 50))}
        >
          上一頁
        </Button>
        <Button disabled={count < 50} onClick={() => setOffset(offset + 50)}>
          下一頁
        </Button>
      </Space>
    </div>
  );
}
export function AuditPage() {
  const data = useData<Items<Audit>>("/audit");
  return (
    <>
      <Heading
        title="操作紀錄"
        note="最近 100 筆管理與資料操作紀錄。紀錄不包含原始密碼、憑證或訊息正文。"
        extra={<Button onClick={() => data.refetch()}>重新整理</Button>}
      />
      <Load query={data}>
        <Table
          rowKey="id"
          dataSource={data.data?.items}
          scroll={{ x: 850 }}
          expandable={{
            expandedRowRender: (r) => (
              <pre>
                {JSON.stringify(
                  { request_id: r.request_id, details: r.details },
                  null,
                  2,
                )}
              </pre>
            ),
          }}
          columns={[
            { title: "時間", dataIndex: "created_at", render: when },
            { title: "操作", dataIndex: "action" },
            {
              title: "執行者",
              dataIndex: "actor_id",
              render: (id) => <ID value={id} />,
            },
            {
              title: "對象",
              dataIndex: "target_id",
              render: (id) => <ID value={id} />,
            },
          ]}
        />
      </Load>
    </>
  );
}
