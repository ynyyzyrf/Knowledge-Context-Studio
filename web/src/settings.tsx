import { useSearchParams } from "react-router-dom";
import { Alert } from "antd";
import { Cognition } from "./cognition";
import { Developer } from "./developer";
import { Jobs } from "./pages";
import { useWorkspace } from "./shared";

const tabs = [
  { key: "jobs", label: "任務中心" },
  { key: "cognition", label: "記憶治理" },
  { key: "api", label: "API 接入測試" },
];

export function Settings() {
  const { tenant } = useWorkspace();
  const admin = tenant.role === "tenant_admin";
  const [params, setParams] = useSearchParams();
  const allowed = admin ? tabs : tabs.filter((t) => t.key === "api");
  const current = allowed.some((t) => t.key === params.get("tab"))
    ? params.get("tab")!
    : allowed[0].key;
  return (
    <div className="settings-page">
      <div className="page-heading">
        <div>
          <h1>設定</h1>
          <p>治理與開發者工具集中在此；它們是公司級能力，不屬於單一知識空間。</p>
        </div>
      </div>
      {!admin && (
        <Alert
          type="info"
          showIcon
          message="任務中心與記憶治理由團隊管理員操作；你可使用 API 接入測試驗證自己的接入。"
        />
      )}
      <div className="settings-tabs">
        {allowed.map((t) => (
          <button
            key={t.key}
            className={t.key === current ? "active" : ""}
            onClick={() => setParams({ tab: t.key })}
          >
            {t.label}
          </button>
        ))}
      </div>
      {current === "jobs" && <Jobs />}
      {current === "cognition" && <Cognition />}
      {current === "api" && <Developer />}
    </div>
  );
}
