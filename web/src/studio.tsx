import { PrivateResourceAccess } from "./private-resource-access";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Alert, Button, Input, Tag, Tabs, Typography } from "antd";
import {
  LeftOutlined,
  PlusOutlined,
  SearchOutlined,
  FolderOpenOutlined,
  CloudUploadOutlined,
  ApiOutlined,
  BookOutlined,
} from "@ant-design/icons";
import {
  ContextReader,
  ContextTree,
  selectionKey,
  type Selection,
} from "./context-browser";
import { Documents } from "./documents";
import { activeField, roleOptions } from "./pages";
import {
  Blank,
  Dot,
  ID,
  Load,
  Problem,
  Status,
  ago,
  useData,
  useForms,
  useWorkspace,
  useWrite,
  when,
} from "./shared";
import { request } from "./api";
import type { SearchHit, Space as SpaceType, SpaceContext } from "./types";

type Section = "overview" | "search" | "upload" | "agents";

type DocDetail = {
  id: string;
  filename: string;
  resource_path: string;
  location: string;
  scope: "private" | "shared";
  byte_size: number;
  checksum: string;
  state: string;
  deleted: boolean;
  chunk_count: number;
  created_at: number;
  chunks: { number: number; page: number | null; content: string }[];
  has_more: boolean;
};

const sectionIcons = {
  overview: <FolderOpenOutlined />,
  search: <SearchOutlined />,
  upload: <CloudUploadOutlined />,
  agents: <ApiOutlined />,
};

const sectionLabels: Record<Section, string> = {
  overview: "文件概覽",
  search: "檢索",
  upload: "上傳",
  agents: "Agent 接入",
};

export function SpaceStudio({ spaceId }: { spaceId: string }) {
  const { tenant } = useWorkspace();
  const admin = tenant.role === "tenant_admin";
  const navigate = useNavigate();
  const [section, setSection] = useState<Section>("overview");
  const [selection, setSelection] = useState<Selection>({ type: "overview" });
  const [hit, setHit] = useState<SearchHit | null>(null);
  const space = useData<SpaceType>(`/spaces/${spaceId}`);
  const context = useData<SpaceContext>(`/spaces/${spaceId}/context`);
  const pick = (next: Selection) => {
    setSelection(next);
    setSection("overview");
  };
  const sync = space.data?.sync_state;
  const wide = section === "upload" || section === "agents";
  return (
    <div className={`studio${wide ? " studio-wide" : ""}`}>
      <a className="skip-link" href="#studio-content">
        跳至主要內容
      </a>
      <aside className="studio-nav">
        <Link className="back-link" to="/spaces">
          <LeftOutlined /> 返回所有空間
        </Link>
        <div className="studio-space">
          <div className="space-emblem" aria-hidden="true">
            <BookOutlined />
          </div>
          <h2>{space.data?.name ?? "…"}</h2>
          <span>Knowledge Space</span>
          {sync && <Dot value={sync} />}
        </div>
        <nav className="studio-menu">
          {(Object.keys(sectionLabels) as Section[]).map((key) => (
            <button
              key={key}
              aria-current={key === section ? "page" : undefined}
              className={key === section ? "active" : ""}
              onClick={() => {
                setSection(key);
                setSelection({ type: "overview" });
                setHit(null);
              }}
            >
              {sectionIcons[key]}
              <span>{sectionLabels[key]}</span>
            </button>
          ))}
        </nav>
      </aside>
      <section id="studio-content" className="studio-mid">
        <header className="studio-section-heading">
          <span>知識空間</span>
          <h1>{sectionLabels[section]}</h1>
          <p>
            {section === "overview"
              ? "瀏覽私人資料與空間共享知識"
              : section === "upload"
                ? "選擇保存位置，匯入你的知識資料。"
                : section === "search"
                  ? "從此空間的授權資料中查找答案。"
                  : "管理此空間的外部 Agent 存取權。"}
          </p>
        </header>
        {sync === "failed" && (
          <Alert
            type="warning"
            showIcon
            message="引擎同步失敗，請檢查引擎服務後重試；現有文件狀態見「上傳」。"
          />
        )}
        {section === "overview" && (
          <Load query={context}>
            <ContextTree
              context={context.data}
              selection={selection}
              onSelect={pick}
              onUpload={() => setSection("upload")}
              onRefresh={() => {
                void context.refetch();
                void space.refetch();
              }}
              refreshing={context.isFetching}
            />
          </Load>
        )}
        {section === "search" && (
          <SearchPanel spaceId={spaceId} onPick={setHit} />
        )}
        {section === "upload" && <Documents spaceId={spaceId} />}
        {section === "agents" &&
          (admin ? (
            <AgentGrants spaceId={spaceId} context={context.data} />
          ) : (
            <Load query={context}>
              <p className="muted">
                本空間已接入 Agent：
                {context.data?.agents.map((a) => a.agent_name).join("、") ||
                  "無"}
                。授權由團隊管理員管理。
              </p>
            </Load>
          ))}
      </section>
      {!wide && (
        <section className="studio-detail">
          {section === "overview" && (
            <ContextReader
              onSelect={pick}
              key={selectionKey(selection)}
              spaceId={spaceId}
              space={space.data}
              context={context.data}
              selection={selection}
            >
              <DetailPanel
                spaceId={spaceId}
                space={space.data}
                context={context.data}
                selection={selection}
                onSelect={pick}
              />
            </ContextReader>
          )}
          {section === "search" &&
            (hit ? (
              <HitDetail spaceId={spaceId} hit={hit} />
            ) : (
              <aside className="detail-empty">
                <p className="muted">在左側選擇一筆檢索結果查看內容。</p>
              </aside>
            ))}
        </section>
      )}
    </div>
  );
}

function DetailPanel({
  spaceId,
  space,
  context,
  selection,
  onSelect,
}: {
  spaceId: string;
  space?: SpaceType;
  context?: SpaceContext;
  selection: Selection;
  onSelect: (s: Selection) => void;
}) {
  if (selection.type === "overview" && space)
    return (
      <div className="detail">
        <h3>{space.name}</h3>
        <p className="muted">{space.description || "尚未填寫描述"}</p>
        <dl className="kv">
          <dt>狀態</dt>
          <dd>
            <Dot value={space.sync_state} />
          </dd>
          <dt>文件</dt>
          <dd>{space.document_count ?? 0}</dd>
          <dt>Memory</dt>
          <dd>{space.memory_count ?? 0}</dd>
          <dt>已接入 Agent</dt>
          <dd>{space.agent_count ?? 0}</dd>
          <dt>最近更新</dt>
          <dd>{ago(space.last_activity_at)}</dd>
        </dl>
        <h4>可存取此空間的 Agent</h4>
        {context?.agents.length ? (
          <ul className="plain-list">
            {context.agents.map((a) => (
              <li key={a.agent_id}>
                {a.agent_name} {!a.agent_active && <Tag>Agent 已停用</Tag>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">尚未授權任何 Agent。</p>
        )}
        <Alert
          type="info"
          message="不同知識空間之間的文件、記憶、向量索引、檢索與 Agent 權限預設完全隔離。Agent 的跨空間查詢由後端分空間檢索後合併，不會全公司搜尋再過濾。"
        />
      </div>
    );
  if (selection.type === "resources" && context)
    return (
      <div className="detail">
        <h3>resources</h3>
        <p className="muted">
          {selection.scope === "private"
            ? "目前登入使用者的私人知識資料。"
            : "此空間的共享知識。"}
        </p>
        <dl className="kv">
          <dt>URI</dt>
          <dd>
            <code>
              {selection.scope === "private"
                ? "user/default/resources"
                : "resources"}
            </code>
          </dd>
          <dt>分類數</dt>
          <dd>
            {
              context.categories.filter(
                (c) => c.scope === (selection.scope || "shared"),
              ).length
            }
          </dd>
          <dt>文件數</dt>
          <dd>
            {context.categories
              .filter((c) => c.scope === (selection.scope || "shared"))
              .reduce((s, c) => s + c.document_count, 0)}
          </dd>
        </dl>
        <h4>分類</h4>
        <ul className="plain-list">
          {context.categories
            .filter((c) => c.scope === (selection.scope || "shared"))
            .map((c) => (
              <li key={c.key}>
                <Button
                  type="link"
                  size="small"
                  onClick={() =>
                    onSelect({ type: "category", key: c.key, scope: c.scope })
                  }
                >
                  {c.key || "resources（根目錄）"}
                </Button>
                <span className="muted">{c.document_count} 文件</span>
              </li>
            ))}
          {!context.categories.filter(
            (c) => c.scope === (selection.scope || "shared"),
          ).length && <li className="muted">尚無分類</li>}
        </ul>
      </div>
    );
  if (selection.type === "category" && context) {
    const category = context.categories.find(
      (c) =>
        c.key === selection.key && c.scope === (selection.scope || "shared"),
    );
    if (!category) return <Blank text="此分類不存在" />;
    const latest = Math.max(...category.recent.map((d) => d.created_at), 0);
    return (
      <div className="detail">
        <h3>{category.key || "resources（根目錄）"}</h3>
        <dl className="kv">
          <dt>URI</dt>
          <dd>
            <code>
              {category.scope === "private"
                ? "user/default/resources"
                : "resources"}
              /{category.key}
            </code>
          </dd>
          <dt>文件數</dt>
          <dd>{category.document_count}</dd>
          <dt>索引片段</dt>
          <dd>{category.chunk_count}</dd>
          <dt>最近更新</dt>
          <dd>{ago(latest || null)}</dd>
        </dl>
        <h4>最近文件</h4>
        <ul className="plain-list">
          {category.recent.map((d) => (
            <li key={d.id}>
              <Button
                type="link"
                size="small"
                onClick={() => onSelect({ type: "document", id: d.id })}
              >
                {d.filename}
              </Button>
              <span className="muted">{when(d.created_at)}</span>
            </li>
          ))}
        </ul>
        <h4>可讀 Agent</h4>
        {category.scope === "private" ? (
          <PrivateResourceAccess spaceId={spaceId} />
        ) : (
          <AgentReaders context={context} />
        )}
      </div>
    );
  }
  if (selection.type === "document")
    return (
      <DocumentDetail
        key={selection.id}
        spaceId={spaceId}
        id={selection.id}
        context={context}
      />
    );
  if (selection.type === "subjects" && context)
    return (
      <div className="detail">
        <h3>subjects</h3>
        <p className="muted">
          接入此空間的 Agent 與認知主體。每個主體擁有獨立的 memories、peers 與
          sessions。
        </p>
        <dl className="kv">
          <dt>URI</dt>
          <dd>
            <code>context://subjects</code>
          </dd>
          <dt>主體數</dt>
          <dd>{context.subjects.length}</dd>
        </dl>
        <ul className="plain-list">
          {context.subjects.map((s) => (
            <li key={s.id}>
              <Button
                type="link"
                size="small"
                onClick={() => onSelect({ type: "subject", id: s.id })}
              >
                {s.name}
              </Button>
              <span className="muted">
                {s.agent_name} · {s.memory_count} Memory
              </span>
            </li>
          ))}
        </ul>
      </div>
    );
  if (selection.type === "subject-folder" && context) {
    const subject = context.subjects.find((s) => s.id === selection.id);
    if (!subject) return <Blank text="此服務對象不存在" />;
    return (
      <div className="detail">
        <h3>
          {subject.name} / {selection.folder}
        </h3>
        <dl className="kv">
          <dt>所屬 Agent</dt>
          <dd>{subject.agent_name}</dd>
          <dt>{selection.folder === "memories" ? "有效記憶" : "會話數"}</dt>
          <dd>
            {selection.folder === "memories"
              ? subject.memory_count
              : subject.session_count}
          </dd>
        </dl>
        <p className="muted">
          此處顯示目錄統計；內容管理請使用設定中的記憶治理或任務中心。
        </p>
      </div>
    );
  }
  if (selection.type === "subject" && context) {
    const subject = context.subjects.find((s) => s.id === selection.id);
    if (!subject) return <Blank text="此主體不存在" />;
    return (
      <div className="detail">
        <h3>{subject.name}</h3>
        <p className="muted">服務對象 · 所屬 Agent：{subject.agent_name}</p>
        <dl className="kv">
          <dt>Subject ID</dt>
          <dd>
            <ID value={subject.id} />
          </dd>
          <dt>Memory 數</dt>
          <dd>{subject.memory_count}</dd>
          <dt>Peer 數</dt>
          <dd>—</dd>
          <dt>Session 數</dt>
          <dd>{subject.session_count}</dd>
          <dt>狀態</dt>
          <dd>
            <Status value={subject.active ? "active" : "disabled"} />
          </dd>
        </dl>
        <h4>Scope</h4>
        <dl className="kv scope">
          <dt>read</dt>
          <dd>
            <code>resources/*</code>
            <br />
            <code>subjects/{subject.name}/peers/*</code>
          </dd>
          <dt>write</dt>
          <dd>
            <code>subjects/{subject.name}/memories/*</code>
            <br />
            <code>subjects/{subject.name}/sessions/*</code>
          </dd>
        </dl>
        <Alert
          type="info"
          message="共享 resources/* 預設不可寫；寫入僅限該主體自己的記憶與會話。"
        />
      </div>
    );
  }
  return null;
}

function AgentReaders({ context }: { context: SpaceContext }) {
  if (!context.agents.length)
    return <p className="muted">尚未授權任何 Agent。</p>;
  return (
    <ul className="plain-list">
      {context.agents.map((a) => (
        <li key={a.agent_id}>
          {a.agent_name}
          {!a.agent_active && <Tag>Agent 已停用</Tag>}
        </li>
      ))}
    </ul>
  );
}

function DocumentDetail({
  spaceId,
  id,
  context,
}: {
  spaceId: string;
  id: string;
  context?: SpaceContext;
}) {
  const [tab, setTab] = useState("basic");
  const [summary, setSummary] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const { profile, tenant } = useWorkspace();
  const path = `/spaces/${spaceId}/documents/${id}`;
  const data = useData<DocDetail>(path);
  const content = useData<{
    pages: { page: number | null; content: string }[];
  }>(`${path}/content`, tab === "full");
  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await request<{ summary: string }>(
        `/v1/tenants/${tenant.tenant_id}${path}/summary`,
        "POST",
        {},
        { csrf: profile.csrf_token },
      );
      setSummary(result.summary);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="document-detail">
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: "basic",
            label: "基本信息",
            children: (
              <div className="detail">
                <Load query={data}>
                  <h3>{data.data?.filename}</h3>
                  <dl className="kv">
                    <dt>URI</dt>
                    <dd>
                      <code>
                        {data.data?.location}/{data.data?.filename}
                      </code>
                    </dd>
                    <dt>狀態</dt>
                    <dd>
                      <Dot
                        value={
                          data.data?.deleted
                            ? "deleted"
                            : data.data?.state || ""
                        }
                      />
                    </dd>
                    <dt>保存目錄</dt>
                    <dd>{data.data?.location}/</dd>
                    <dt>大小</dt>
                    <dd>
                      {data.data ? Math.ceil(data.data.byte_size / 1024) : 0} KB
                    </dd>
                    <dt>索引片段</dt>
                    <dd>{data.data?.chunk_count}</dd>
                    <dt>匯入時間</dt>
                    <dd>{data.data ? when(data.data.created_at) : ""}</dd>
                    <dt>Checksum</dt>
                    <dd>
                      <Typography.Text
                        className="id"
                        copyable={{ text: data.data?.checksum }}
                      >
                        {(data.data?.checksum || "").slice(0, 12)}…
                      </Typography.Text>
                    </dd>
                  </dl>
                  <h4>可讀 Agent</h4>
                  {data.data?.scope === "private" ? (
                    <PrivateResourceAccess spaceId={spaceId} />
                  ) : (
                    context && <AgentReaders context={context} />
                  )}
                </Load>
              </div>
            ),
          },
          {
            key: "overview",
            label: "概覽信息",
            children: (
              <div className="detail document-summary">
                <h3>文件概覽</h3>
                <p className="muted">
                  使用已配置的模型，依據整份文件生成內容摘要。長文件會分段整理後合併。
                </p>
                {error ? <Problem error={error} /> : null}
                {summary && <div className="document-fulltext">{summary}</div>}
                <Button
                  type="primary"
                  loading={busy}
                  onClick={generate}
                  disabled={data.data?.deleted}
                >
                  {busy
                    ? "正在生成摘要"
                    : summary
                      ? "重新生成摘要"
                      : "生成內容摘要"}
                </Button>
                {summary && (
                  <p className="muted">
                    模型生成，請以完整信息中的原文為準。摘要保留至離開此文件。
                  </p>
                )}
              </div>
            ),
          },
          {
            key: "full",
            label: "完整信息",
            children: (
              <div className="detail">
                <Load query={content}>
                  <h3>{data.data?.filename}</h3>
                  <p className="muted">
                    顯示整份文件的文字內容；PDF
                    按原頁碼排列，不包含圖片與原始版面。
                  </p>
                  {content.data?.pages.map((p, i) => (
                    <section key={i} className="document-text-page">
                      {p.page !== null && <h4>第 {p.page} 頁</h4>}
                      <div className="document-fulltext">{p.content}</div>
                    </section>
                  ))}
                </Load>
              </div>
            ),
          },
        ]}
      />
    </div>
  );
}

function SearchPanel({
  spaceId,
  onPick,
}: {
  spaceId: string;
  onPick: (hit: SearchHit | null) => void;
}) {
  const { profile, tenant } = useWorkspace();
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await request<{ items: SearchHit[] }>(
        `/v1/tenants/${tenant.tenant_id}/spaces/${spaceId}/search`,
        "POST",
        { query },
        { csrf: profile.csrf_token },
      );
      setHits(result.items);
      onPick(null);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="search-panel">
      <h3>空間內檢索</h3>
      <p className="muted">
        只檢索此知識空間的向量索引；其他空間的內容不會出現在結果中。
      </p>
      {error ? <Problem error={error} /> : null}
      <Input.Search
        aria-label="檢索查詢"
        placeholder="輸入查詢，例如：支援時間"
        enterButton={
          <Button type="primary" icon={<SearchOutlined />} loading={busy}>
            檢索
          </Button>
        }
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onSearch={run}
      />
      {hits === null ? null : hits.length ? (
        <ul className="hit-list">
          {hits.map((hit) => (
            <li key={hit.document_id + ":" + hit.chunk}>
              <button onClick={() => onPick(hit)}>
                <strong>{hit.filename}</strong>
                <span className="muted">
                  片段 {hit.chunk + 1}
                  {hit.page ? ` · 第 ${hit.page} 頁` : ""}
                </span>
                <p>{(hit.content || "").slice(0, 120)}…</p>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <Blank text="沒有符合的內容。索引尚未完成時，文件不會出現在結果中。" />
      )}
    </div>
  );
}

function HitDetail({ spaceId, hit }: { spaceId: string; hit: SearchHit }) {
  void spaceId;
  return (
    <div className="detail">
      <h3 title={hit.filename}>{hit.filename}</h3>
      <dl className="kv">
        <dt>片段</dt>
        <dd>
          {hit.chunk + 1}
          {hit.page ? ` · 第 ${hit.page} 頁` : ""}
        </dd>
        <dt>相關度</dt>
        <dd>{hit.score.toFixed(3)}</dd>
      </dl>
      <h4>內容</h4>
      <div className="memory-text hit-content">{hit.content}</div>
    </div>
  );
}

function AgentGrants({
  spaceId,
  context,
}: {
  spaceId: string;
  context?: SpaceContext;
}) {
  const grants = useData<{
    people: { person_id: string; level: string; active: boolean }[];
    agents: { agent_id: string; active: boolean }[];
  }>(`/spaces/${spaceId}/grants`);
  const people = useData<{
    items: { person_id: string; email: string; active: boolean }[];
  }>("/members");
  const agents = useData<{
    items: { id: string; name: string; active: boolean }[];
  }>("/agents");
  const write = useWrite();
  const forms = useForms();
  const navigate = useNavigate();
  return (
    <div className="grant-panel">
      <h3>Agent 授權</h3>
      <p className="muted">
        Agent 必須明確授權才能存取此空間；撤銷後立即無法再檢索。
      </p>
      <Button
        icon={<PlusOutlined />}
        onClick={() =>
          forms.open({
            title: "授權外部 Agent 存取此空間",
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
              write(`/spaces/${spaceId}/agents/${v.agent_id}`, "PUT", {
                active: v.active === "yes",
              }),
          })
        }
      >
        設定 Agent 授權
      </Button>
      <Load query={grants}>
        <ul className="plain-list">
          {grants.data?.agents.map((g) => (
            <li key={g.agent_id}>
              <Button
                type="link"
                size="small"
                onClick={() => navigate("/agents")}
              >
                {agents.data?.items.find((a) => a.id === g.agent_id)?.name ||
                  g.agent_id.slice(0, 8)}
              </Button>
              <Status value={g.active ? "active" : "disabled"} />
            </li>
          ))}
          {!grants.data?.agents.length && (
            <li className="muted">尚未授權任何 Agent。</li>
          )}
        </ul>
        <h3>成員授權</h3>
        <Button
          onClick={() =>
            forms.open({
              title: "設定成員授權",
              fields: [
                {
                  name: "person_id",
                  label: "團隊成員",
                  type: "select",
                  options: people.data?.items
                    .filter((x) => x.active)
                    .map((x) => ({ value: x.person_id, label: x.email })),
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
                write(`/spaces/${spaceId}/people/${v.person_id}`, "PUT", {
                  level: v.level,
                  active: v.active === "yes",
                }),
            })
          }
        >
          設定成員授權
        </Button>
        <ul className="plain-list">
          {grants.data?.people.map((g) => (
            <li key={g.person_id}>
              {people.data?.items.find((p) => p.person_id === g.person_id)
                ?.email || g.person_id.slice(0, 8)}
              <Status value={g.level} />
              <Status value={g.active ? "active" : "disabled"} />
            </li>
          ))}
          {!grants.data?.people.length && (
            <li className="muted">尚未授權任何成員。</li>
          )}
        </ul>
        <p className="muted">
          此空間主體：
          {context?.subjects.map((s) => s.name).join("、") || "尚無"}
        </p>
      </Load>
      {forms.modal}
    </div>
  );
}
