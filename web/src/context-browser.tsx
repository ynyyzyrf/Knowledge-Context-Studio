import { PrivateResourceAccess } from "./private-resource-access";
import { useRef, useState, type ReactNode, type Key } from "react";
import { Button, Input, Tree, Typography, type InputRef } from "antd";
import {
  DownOutlined,
  FileTextOutlined,
  FolderOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  ArrowRightOutlined,
  LockOutlined,
  TeamOutlined,
} from "@ant-design/icons";
import type { DataNode } from "antd/es/tree";
import type { Space, SpaceContext } from "./types";

export type Selection =
  | { type: "overview" }
  | { type: "user" | "default" }
  | { type: "namespace-folder"; folder: string }
  | { type: "resources"; scope?: "private" | "shared" }
  | { type: "category"; key: string; scope?: "private" | "shared" }
  | { type: "document"; id: string }
  | { type: "subjects" }
  | { type: "subject"; id: string }
  | { type: "subject-folder"; id: string; folder: "memories" | "sessions" };

export function selectionKey(s: Selection): string {
  if (s.type === "category") return `category:${s.scope || "shared"}:${s.key}`;
  if (s.type === "resources") return `resources:${s.scope || "shared"}`;
  if (s.type === "namespace-folder") return `namespace:${s.folder}`;
  if (s.type === "subject-folder") return `subject:${s.id}:${s.folder}`;
  return "id" in s ? `${s.type}:${s.id}` : s.type;
}
type Node = DataNode & {
  searchText: string;
  selection?: Selection;
  children?: Node[];
};

export function ContextTree({
  context,
  selection,
  onSelect,
  onUpload,
  onRefresh,
  refreshing,
}: {
  context?: SpaceContext;
  selection: Selection;
  onSelect: (s: Selection) => void;
  onUpload: () => void;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Key[]>([
    "user",
    "default",
    "resources:private",
    "resources:shared",
    ...(context?.subjects.map((s) => `subject:${s.id}`) || []),
  ]);
  const input = useRef<InputRef>(null);
  const empty = (key: string, text: string): Node => ({
    key,
    title: <span className="browser-empty">{text}</span>,
    searchText: "",
    selectable: false,
    isLeaf: true,
  });
  const node = (
    s: Selection,
    name: string,
    description: string,
    count?: number,
    children?: Node[],
  ): Node => ({
    key: selectionKey(s),
    selection: s,
    searchText: `${name} ${description}`,
    icon: s.type === "document" ? <FileTextOutlined /> : <FolderOutlined />,
    title: (
      <span className="browser-node" title={`${name} · ${description}`}>
        <strong>{name}</strong>
        <span>{description}</span>
        {count !== undefined && <small>{count}</small>}
      </span>
    ),
    isLeaf: !children?.length,
    children,
  });
  const resources = (scope: "private" | "shared", parent: string): Node[] => {
    const root = context?.categories.find(
      (c) => c.key === parent && c.scope === scope,
    );
    const folders = (context?.categories || []).filter(
      (c) =>
        c.scope === scope &&
        c.key &&
        c.key.split("/").slice(0, -1).join("/") === parent,
    );
    const result: Node[] = folders.map((c) =>
      node(
        { type: "category", key: c.key, scope },
        c.key.split("/").pop()!,
        "資料夾",
        c.document_count,
        resources(scope, c.key),
      ),
    );
    result.push(
      ...(root?.recent || []).map((d) =>
        node({ type: "document", id: d.id }, d.filename, ""),
      ),
    );
    if (root && root.document_count > root.recent.length)
      result.push({
        key: `more:${scope}:${parent}`,
        searchText: "",
        selectable: false,
        isLeaf: true,
        title: (
          <Button type="link" size="small" onClick={onUpload}>
            查看全部文件
          </Button>
        ),
      });
    return result.length
      ? result
      : [empty(`empty:${scope}:${parent}`, "此資料夾尚無文件")];
  };
  const count = (scope: string) =>
    context?.categories
      .filter((c) => c.scope === scope)
      .reduce((n, c) => n + c.document_count, 0) || 0;
  const personal = (folder: string, description: string) =>
    node({ type: "namespace-folder", folder }, folder, description, undefined, [
      empty(`namespace-empty:${folder}`, "尚未接入此個人目錄"),
    ]);
  const nodes: Node[] = [
    node({ type: "user" }, "user", "", undefined, [
      node(
        { type: "default" },
        "default",
        "目前登入使用者的上下文",
        undefined,
        [
          personal("memories", "跨會話沉澱的長期記憶"),
          personal("peers", "服務對象、應用與工作區上下文"),
          personal("privacy", "私密配置 · 不參與檢索"),
          node(
            { type: "resources", scope: "private" },
            "resources",
            "我的私人知識資料",
            count("private"),
            resources("private", ""),
          ),
          personal("sessions", "對話與任務運行紀錄"),
          personal("skills", "可使用的技能與工具"),
        ],
      ),
    ]),
    node(
      { type: "resources", scope: "shared" },
      "resources",
      "此空間的共享知識",
      count("shared"),
      resources("shared", ""),
    ),
  ];
  const needle = query.trim().toLocaleLowerCase();
  const filter = (items: Node[]): Node[] =>
    items.flatMap((n) => {
      if (n.searchText.toLocaleLowerCase().includes(needle)) return [n];
      const children = n.children ? filter(n.children) : [];
      return children.length ? [{ ...n, children }] : [];
    });
  const visible = needle ? filter(nodes) : nodes;
  const keys = (items: Node[]): Key[] =>
    items.flatMap((n) => [n.key, ...keys(n.children || [])]);
  return (
    <div className="context-browser">
      <div
        className="browser-toolbar"
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
            e.preventDefault();
            input.current?.focus();
          }
        }}
      >
        <Input
          ref={input}
          allowClear
          prefix={<SearchOutlined />}
          aria-label="篩選目錄與近期文件"
          placeholder="篩選目錄與近期文件"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <Button
          aria-label="匯入文件"
          title="匯入文件"
          icon={<PlusOutlined />}
          onClick={onUpload}
        />
        <Button
          aria-label="重新載入目錄"
          title="重新載入目錄"
          icon={<ReloadOutlined />}
          loading={refreshing}
          onClick={onRefresh}
        />
      </div>
      <p className="browser-caption">空間目錄 · 每個分類顯示最近 5 份文件</p>
      {visible.length ? (
        <Tree
          blockNode
          showIcon
          showLine={{ showLeafIcon: false }}
          switcherIcon={<DownOutlined />}
          treeData={visible}
          expandedKeys={needle ? keys(visible) : expanded}
          onExpand={setExpanded}
          selectedKeys={[selectionKey(selection)]}
          onSelect={(_, info) => {
            const next = (info.node as Node).selection;
            if (next) onSelect(next);
          }}
        />
      ) : (
        <p className="browser-empty">沒有符合的目錄或近期文件。</p>
      )}
    </div>
  );
}

export function ContextReader({
  spaceId,
  space,
  context,
  selection,
  children,
  onSelect,
}: {
  spaceId: string;
  space?: Space;
  context?: SpaceContext;
  selection: Selection;
  children: ReactNode;
  onSelect: (selection: Selection) => void;
}) {
  const [view, setView] = useState("overview");
  const subject =
    "id" in selection
      ? context?.subjects.find((s) => s.id === selection.id)
      : undefined;
  const category =
    selection.type === "category"
      ? context?.categories.find(
          (c) =>
            c.key === selection.key &&
            c.scope === (selection.scope || "shared"),
        )
      : undefined;
  const document =
    selection.type === "document"
      ? context?.categories
          .flatMap((c) => c.recent)
          .find((d) => d.id === selection.id)
      : undefined;
  let name = space?.name || "知識空間";
  let suffix = "";
  let summary =
    space?.description ||
    "在左側選擇資料夾或文件，瀏覽此空間的私人與共享知識。";
  if (selection.type === "user" || selection.type === "default") {
    name = selection.type;
    suffix = selection.type === "user" ? "/user" : "/user/default";
    summary =
      "default 由後端依登入身份解析，代表你在目前知識空間的私人上下文。每個使用者、每個空間分別隔離。";
  }
  if (selection.type === "namespace-folder") {
    name = selection.folder;
    suffix = `/user/default/${name}`;
    summary =
      name === "privacy"
        ? "私人敏感配置目錄，不參與普通知識檢索。目前尚未開放寫入。"
        : "此個人目錄尚未接入資料。現有服務對象的記憶與會話仍由原有治理功能管理，不會自動歸入目前登入使用者。";
  }
  if (selection.type === "resources") {
    name = "resources";
    const scope = selection.scope || "shared";
    suffix = scope === "private" ? "/user/default/resources" : "/resources";
    summary =
      scope === "private"
        ? "你在此知識空間的私人知識資料。一般上傳預設保存到此處。Agent 必須使用綁定你的 Token，並取得你的私人資源讀取授權。"
        : "目前知識空間的共享知識資料，提供給具有此空間存取權限的 Agent。上傳時須明確選擇共享知識。";
  }
  if (selection.type === "subjects") {
    name = "subjects";
    suffix = "/subjects";
    summary = `此空間已接入 ${context?.subjects.length ?? 0} 個服務對象。每個對象的記憶與會話分別管理，所屬 Agent 顯示在目錄中。`;
  }
  if (selection.type === "category") {
    name = selection.key.split("/").pop() || "resources";
    suffix = `${selection.scope === "private" ? "/user/default/resources" : "/resources"}/${selection.key.split("/").map(encodeURIComponent).join("/")}`;
    summary = `此分類共有 ${category?.document_count ?? 0} 份文件、${category?.chunk_count ?? 0} 個索引片段。展開左側資料夾，可選擇近期文件閱讀解析內容。`;
  }
  if (selection.type === "document") {
    name = document?.filename || "文件";
    suffix = `${document?.scope === "private" ? "/user/default/resources" : "/resources"}/${document?.resource_path ? document.resource_path + "/" : ""}${name}`;
  }
  if (subject) {
    name = subject.name;
    suffix = `/subjects/${subject.id}`;
    summary = `${subject.name} 的上下文資料，所屬 Agent：${subject.agent_name}。目前有 ${subject.memory_count} 筆有效記憶、${subject.session_count} 段會話。`;
    if (selection.type === "subject-folder") {
      name = selection.folder;
      suffix += `/${name}`;
      summary =
        name === "memories"
          ? `跨會話保留的長期記憶。目前 ${subject.memory_count} 筆已生效記憶；候選審核、版本修正與停用在「設定 → 記憶治理」管理。`
          : `由外部 Agent 提交的對話紀錄。目前 ${subject.session_count} 段會話；抽取任務的執行狀態可在「設定 → 任務中心」查看。`;
    }
  }
  const path = `context://spaces/${spaceId}${suffix}`;
  const file = selection.type === "document";
  return (
    <div className="context-reader">
      <header className="reader-heading">
        <Typography.Text className="reader-path" copyable={{ text: path }}>
          <span>
            {suffix
              ? `${space?.name || "知識空間"}${suffix.slice(0, suffix.lastIndexOf("/") + 1)}`
              : "知識空間 / "}
          </span>
          <strong>
            {file ? name : suffix ? name : space?.name || spaceId}
          </strong>
        </Typography.Text>
        <p>
          <span className="reader-kind">{file ? "文件" : "資料夾"}</span>
          <span className="muted">
            {file ? "閱讀已解析的文件內容" : "目錄概覽與詳細資料"}
          </span>
        </p>
      </header>
      <section className="reader-card" aria-label={`${name} 閱讀區`}>
        <div className="reader-tabs" hidden={file}>
          {!file && (
            <>
              <button
                className={`reader-tab ${view === "overview" ? "active" : ""}`}
                onClick={() => setView("overview")}
              >
                概覽
              </button>
              <button
                className={`reader-tab ${view === "details" ? "active" : ""}`}
                onClick={() => setView("details")}
              >
                詳細資料
              </button>
            </>
          )}
          {!file && (
            <Typography.Text
              className="reader-copy"
              copyable={{ text: summary }}
              aria-label="複製目錄說明"
            />
          )}
        </div>
        <div className={file ? "document-reader-body" : "reader-body"}>
          {(file || view === "details") &&
          !["user", "default", "namespace-folder"].includes(selection.type) ? (
            children
          ) : (
            <>
              <h2>{name}</h2>
              <p className="reader-summary">{summary}</p>
              {selection.type === "overview" && (
                <div className="space-overview-body">
                  <div className="overview-metrics">
                    <div>
                      <strong>
                        {context?.categories.reduce(
                          (n, c) => n + c.document_count,
                          0,
                        ) ?? 0}
                      </strong>
                      <span>可讀文件</span>
                    </div>
                    <div>
                      <strong>
                        {context?.agents.filter((a) => a.agent_active).length ??
                          0}
                      </strong>
                      <span>已接入 Agent</span>
                    </div>
                  </div>
                  <h3>從資料目錄開始</h3>
                  <button
                    className="namespace-shortcut"
                    onClick={() =>
                      onSelect({ type: "resources", scope: "private" })
                    }
                  >
                    <span className="shortcut-icon">
                      <LockOutlined />
                    </span>
                    <span>
                      <strong>我的私人知識</strong>
                      <small>user/default/resources</small>
                      <p>一般上傳保存在這裡，由你決定 Agent 的讀取權。</p>
                    </span>
                    <ArrowRightOutlined />
                  </button>
                  <button
                    className="namespace-shortcut"
                    onClick={() =>
                      onSelect({ type: "resources", scope: "shared" })
                    }
                  >
                    <span className="shortcut-icon">
                      <TeamOutlined />
                    </span>
                    <span>
                      <strong>空間共享知識</strong>
                      <small>resources</small>
                      <p>集中管理此空間內可供已授權 Agent 讀取的資料。</p>
                    </span>
                    <ArrowRightOutlined />
                  </button>
                </div>
              )}
              {selection.type === "resources" &&
                selection.scope === "private" && (
                  <PrivateResourceAccess spaceId={spaceId} />
                )}
            </>
          )}
        </div>
      </section>
    </div>
  );
}
