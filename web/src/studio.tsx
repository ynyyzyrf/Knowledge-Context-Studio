import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Alert, Button, Input, Tag, Typography } from "antd";
import { LeftOutlined, PlusOutlined, SearchOutlined } from "@ant-design/icons";
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
type Selection =
  | { type: "overview" }
  | { type: "resources" }
  | { type: "category"; key: string }
  | { type: "document"; id: string }
  | { type: "subjects" }
  | { type: "subject"; id: string };

type DocDetail = {
  id: string;
  filename: string;
  byte_size: number;
  checksum: string;
  state: string;
  deleted: boolean;
  chunk_count: number;
  created_at: number;
  chunks: { number: number; page: number | null; content: string }[];
  has_more: boolean;
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
  return (
    <div className="studio">
      <aside className="studio-nav">
        <Link className="back-link" to="/spaces">
          <LeftOutlined /> 返回所有空間
        </Link>
        <div className="studio-space">
          <h2>{space.data?.name ?? "…"}</h2>
          <span>Knowledge Space</span>
          {sync && <Dot value={sync} />}
        </div>
        <nav className="studio-menu">
          {(Object.keys(sectionLabels) as Section[]).map((key) => (
            <button
              key={key}
              className={key === section ? "active" : ""}
              onClick={() => {
                setSection(key);
                setSelection({ type: "overview" });
                setHit(null);
              }}
            >
              {sectionLabels[key]}
            </button>
          ))}
        </nav>
        <p className="studio-note">
          此空間與其他知識空間預設完全隔離：文件、記憶、向量索引與 Agent
          權限互相獨立。
        </p>
      </aside>
      <section className="studio-mid">
        {sync === "pending" && (
          <Alert
            type="info"
            showIcon
            message="空間索引同步進行中，完成後文件才會提供給已授權 Agent。"
          />
        )}
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
                本空間已接入 Agent：{
                  context.data?.agents.map((a) => a.agent_name).join("、") ||
                  "無"
                }
                。授權由團隊管理員管理。
              </p>
            </Load>
          ))}
      </section>
      <section className="studio-detail">
        {section === "overview" && (
          <DetailPanel
            spaceId={spaceId}
            space={space.data}
            context={context.data}
            selection={selection}
            onSelect={pick}
          />
        )}
        {section === "search" &&
          (hit ? (
            <HitDetail spaceId={spaceId} hit={hit} />
          ) : (
            <aside className="detail-empty">
              <p className="muted">在左側選擇一筆檢索結果查看內容。</p>
            </aside>
          ))}
        {section === "upload" && (
          <aside className="detail-empty">
            <p className="muted">
              支援 .md、.txt 與文字型 PDF。每檔最多 10 MB、100 頁、200,000
              字元；索引完成後，已授權的外部 Agent 才能檢索。
            </p>
          </aside>
        )}
        {section === "agents" &&
          (admin ? (
            <p className="muted">在左側管理此空間的 Agent 與成員授權。</p>
          ) : null)}
      </section>
    </div>
  );
}

function ContextTree({
  context,
  selection,
  onSelect,
}: {
  context?: SpaceContext;
  selection: Selection;
  onSelect: (s: Selection) => void;
}) {
  const documents =
    context?.categories.reduce((sum, c) => sum + c.document_count, 0) ?? 0;
  const cls = (active: boolean) => (active ? "active" : "");
  return (
    <div className="ctree">
      <div className="ctree-root">context://</div>
      <div className="ctree-branch">
        <button
          className={cls(selection.type === "resources")}
          onClick={() => onSelect({ type: "resources" })}
        >
          resources <i>{documents}</i>
        </button>
        <ul>
          {context?.categories.map((c) => (
            <li key={c.key}>
              <button
                className={cls(
                  selection.type === "category" && selection.key === c.key,
                )}
                onClick={() => onSelect({ type: "category", key: c.key })}
              >
                {c.key === "general" ? "未分類" : c.key} <i>{c.document_count}</i>
              </button>
              <ul>
                {c.recent.map((d) => (
                  <li key={d.id}>
                    <button
                      className={
                        "leaf " +
                        cls(selection.type === "document" && selection.id === d.id)
                      }
                      title={d.filename}
                      onClick={() => onSelect({ type: "document", id: d.id })}
                    >
                      {d.filename.split("/").pop()}
                    </button>
                  </li>
                ))}
              </ul>
            </li>
          ))}
          {!context?.categories.length && (
            <li className="dim">尚無文件</li>
          )}
        </ul>
      </div>
      <div className="ctree-branch">
        <button
          className={cls(selection.type === "subjects")}
          onClick={() => onSelect({ type: "subjects" })}
        >
          subjects <i>{context?.subjects.length ?? 0}</i>
        </button>
        <ul>
          {context?.subjects.map((s) => (
            <li key={s.id}>
              <button
                className={cls(
                  selection.type === "subject" && selection.id === s.id,
                )}
                onClick={() => onSelect({ type: "subject", id: s.id })}
              >
                {s.name}
                {!s.active && <Tag className="mini-tag">停用</Tag>}
              </button>
              <ul className="ctree-sub">
                <li>memories <i>{s.memory_count}</i></li>
                <li>peers <i>—</i></li>
                <li>sessions <i>{s.session_count}</i></li>
              </ul>
            </li>
          ))}
          {!context?.subjects.length && <li className="dim">尚無接入主體</li>}
        </ul>
      </div>
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
        <p className="muted">此空間的客觀共享知識，預設對已授權 Agent 唯讀。</p>
        <dl className="kv">
          <dt>URI</dt>
          <dd>
            <code>context://resources</code>
          </dd>
          <dt>分類數</dt>
          <dd>{context.categories.length}</dd>
          <dt>文件數</dt>
          <dd>
            {context.categories.reduce((s, c) => s + c.document_count, 0)}
          </dd>
        </dl>
        <h4>分類</h4>
        <ul className="plain-list">
          {context.categories.map((c) => (
            <li key={c.key}>
              <Button
                type="link"
                size="small"
                onClick={() => onSelect({ type: "category", key: c.key })}
              >
                {c.key === "general" ? "未分類" : c.key}
              </Button>
              <span className="muted">{c.document_count} 文件</span>
            </li>
          ))}
          {!context.categories.length && <li className="muted">尚無分類</li>}
        </ul>
      </div>
    );
  if (selection.type === "category" && context) {
    const category = context.categories.find((c) => c.key === selection.key);
    if (!category) return <Blank text="此分類不存在" />;
    const latest = Math.max(...category.recent.map((d) => d.created_at), 0);
    return (
      <div className="detail">
        <h3>{category.key === "general" ? "未分類" : category.key}</h3>
        <dl className="kv">
          <dt>URI</dt>
          <dd>
            <code>context://resources/{category.key}</code>
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
        <AgentReaders context={context} />
      </div>
    );
  }
  if (selection.type === "document")
    return <DocumentDetail spaceId={spaceId} id={selection.id} context={context} />;
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
  if (selection.type === "subject" && context) {
    const subject = context.subjects.find((s) => s.id === selection.id);
    if (!subject) return <Blank text="此主體不存在" />;
    return (
      <div className="detail">
        <h3>{subject.name}</h3>
        <p className="muted">
          服務對象 · 所屬 Agent：{subject.agent_name}
        </p>
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
  if (!context.agents.length) return <p className="muted">尚未授權任何 Agent。</p>;
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
  const data = useData<DocDetail>(`/spaces/${spaceId}/documents/${id}`);
  return (
    <div className="detail">
      <Load query={data}>
        <h3 title={data.data?.filename}>{data.data?.filename}</h3>
        <dl className="kv">
          <dt>URI</dt>
          <dd>
            <code>context://resources/documents/{id.slice(0, 8)}</code>
          </dd>
          <dt>狀態</dt>
          <dd>
            <Dot value={data.data?.deleted ? "deleted" : data.data?.state || ""} />
          </dd>
          <dt>大小</dt>
          <dd>{data.data ? Math.ceil(data.data.byte_size / 1024) : 0} KB</dd>
          <dt>索引片段</dt>
          <dd>{data.data?.chunk_count}</dd>
          <dt>匯入時間</dt>
          <dd>{data.data ? when(data.data.created_at) : ""}</dd>
          <dt>Checksum</dt>
          <dd>
            <Typography.Text className="id" copyable={{ text: data.data?.checksum }}>
              {(data.data?.checksum || "").slice(0, 12)}…
            </Typography.Text>
          </dd>
        </dl>
        <h4>可讀 Agent</h4>
        {context && <AgentReaders context={context} />}
        <h4>摘要（第一個片段）</h4>
        {data.data?.chunks.map((c) => (
          <div className="memory-reference" key={c.number}>
            <strong>
              片段 {c.number + 1}
              {c.page ? ` · 第 ${c.page} 頁` : ""}
            </strong>
            <p className="memory-text">{c.content}</p>
          </div>
        ))}
        {!data.data?.chunks.length && <p className="muted">尚未有可顯示片段。</p>}
      </Load>
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
  const people = useData<{ items: { person_id: string; email: string; active: boolean }[] }>(
    "/members",
  );
  const agents = useData<{ items: { id: string; name: string; active: boolean }[] }>(
    "/agents",
  );
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
