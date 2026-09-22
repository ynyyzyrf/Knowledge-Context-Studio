import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  matchPath,
  useLocation,
  useNavigate,
} from "react-router-dom";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Alert,
  Button,
  ConfigProvider,
  Form,
  Input,
  Layout,
  Menu,
  Select,
  Space,
  Spin,
} from "antd";
import zhTW from "antd/locale/zh_TW";
import { ApiError, request } from "./api";
import { forgetSession } from "./session";
import { Context, Problem, useWorkspace } from "./shared";
import type { Membership, Profile } from "./types";
import { Agents, Spaces, Members, AuditPage } from "./pages";
import { Settings } from "./settings";
import { SpaceStudio } from "./studio";
import "./style.css";
const client = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 10000, refetchOnWindowFocus: false, retry: false },
  },
});
function Login() {
  const qc = useQueryClient();
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  return (
    <div className="login">
      <section className="login-story">
        <div className="brand">
          <span>K</span> KNOWLEDGE CONTEXT STUDIO
        </div>
        <h1>
          知識有來源。
          <br />
          記憶有邊界。
        </h1>
        <p>
          將團隊知識與外部 Agent 的記憶集中管理，
          <br />
          從授權、提取到審核，每一步都有跡可循。
        </p>
        <div className="login-footer">
          Knowledge Space 隔離 · Agent 授權 · 記憶治理
        </div>
      </section>
      <section className="login-form">
        <div>
          <span className="eyebrow">團隊工作台</span>
          <h2>登入你的工作空間</h2>
          <p className="muted">使用管理員為你開通的帳號。</p>
          {error ? <Problem error={error} /> : null}
          <Form
            layout="vertical"
            onFinish={async (values) => {
              setBusy(true);
              setError(null);
              try {
                const p = await request<Profile>(
                  "/v1/auth/login",
                  "POST",
                  values,
                );
                qc.setQueryData(["profile"], p);
              } catch (e) {
                setError(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            <Form.Item
              name="email"
              label="電子郵件"
              rules={[
                { required: true, type: "email", message: "請輸入有效信箱" },
              ]}
            >
              <Input
                size="large"
                autoComplete="username"
                placeholder="你的信箱"
              />
            </Form.Item>
            <Form.Item
              name="password"
              label="密碼"
              rules={[{ required: true, message: "請輸入密碼" }]}
            >
              <Input.Password size="large" autoComplete="current-password" />
            </Form.Item>
            <Button
              block
              size="large"
              type="primary"
              htmlType="submit"
              loading={busy}
            >
              登入工作台
            </Button>
          </Form>
          <p className="login-help">
            僅供已授權團隊成員使用。首次登入資訊由本機管理員提供。
          </p>
        </div>
      </section>
    </div>
  );
}
function Shell({
  profile,
  tenant,
  onTenant,
}: {
  profile: Profile;
  tenant: Membership;
  onTenant: (x: string) => void;
}) {
  const [token, setToken] = useState("");
  const location = useLocation();
  const spaceMatch = matchPath("/spaces/:spaceId", location.pathname);
  return (
    <Context.Provider value={{ profile, tenant, token, setToken }}>
      {spaceMatch?.params.spaceId ? (
        // Second product layer: a dedicated full-screen studio per space.
        <SpaceStudio spaceId={spaceMatch.params.spaceId} />
      ) : (
        <OrgShell profile={profile} tenant={tenant} onTenant={onTenant} />
      )}
    </Context.Provider>
  );
}
function OrgShell({
  profile,
  tenant,
  onTenant,
}: {
  profile: Profile;
  tenant: Membership;
  onTenant: (x: string) => void;
}) {
  const { setToken } = useWorkspace();
  const [logoutError, setLogoutError] = useState<unknown>();
  const [collapsed, setCollapsed] = useState(false);
  const [narrow, setNarrow] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const admin = tenant.role === "tenant_admin";
  const items = [
    {
      key: "workspace",
      type: "group" as const,
      label: "工作區",
      children: [
        { key: "/spaces", label: "知識空間" },
        ...(admin ? [{ key: "/agents", label: "外部 Agent 接入" }] : []),
      ],
    },
    {
      key: "admin",
      type: "group" as const,
      label: "管理",
      children: [
        { key: "/members", label: "團隊成員" },
        ...(admin ? [{ key: "/audit", label: "操作紀錄" }] : []),
        { key: "/settings", label: "設定" },
      ],
    },
  ];
  return (
    <Layout className="workspace">
      <Layout.Sider
          breakpoint="lg"
          onBreakpoint={setNarrow}
          collapsedWidth={0}
          collapsed={collapsed}
          onCollapse={setCollapsed}
          width={224}
          theme="light"
        >
          <div className="sidebar-brand">
            <b>K</b>
            <div>
              Knowledge Context<span>CONTEXT STUDIO</span>
            </div>
          </div>
          <Menu
            mode="inline"
            selectedKeys={["/" + location.pathname.split("/")[1]]}
            items={items}
            onClick={({ key }) => {
              navigate(key);
              if (narrow) setCollapsed(true);
            }}
          />
        </Layout.Sider>
        <Layout>
          <header className="topbar">
            <Select
              aria-label="選擇團隊"
              value={tenant.tenant_id}
              options={profile.memberships.map((m) => ({
                value: m.tenant_id,
                label: m.name,
              }))}
              onChange={async (value) => {
                setToken("");
                await qc.cancelQueries();
                qc.removeQueries({ queryKey: ["tenant"] });
                qc.removeQueries({ queryKey: ["machine"] });
                onTenant(value);
                navigate("/spaces");
              }}
            />
            <Space>
              <span className="account-email">{profile.person.email}</span>
              <Button
                onClick={async () => {
                  try {
                    await request("/v1/auth/logout", "POST", undefined, {
                      csrf: profile.csrf_token,
                    });
                    setToken("");
                    forgetSession(qc);
                  } catch (e) {
                    setLogoutError(e);
                  }
                }}
              >
                登出
              </Button>
            </Space>
          </header>
          <main className="content">
            {logoutError ? <Problem error={logoutError} /> : null}
            <Routes>
              <Route path="/spaces" element={<Spaces />} />
              <Route path="/members" element={<Members />} />
              <Route path="/settings" element={<Settings />} />
              {admin && (
                <>
                  <Route path="/agents" element={<Agents />} />
                  <Route path="/audit" element={<AuditPage />} />
                </>
              )}
              <Route path="*" element={<Navigate to="/spaces" replace />} />
            </Routes>
          </main>
          <footer className="workspace-footer">
            Knowledge Context Studio · 內部版本{" "}
            <span>Knowledge Space 是知識與 Context 的最高隔離單元</span>
          </footer>
        </Layout>
      </Layout>
  );
}
function App() {
  const qc = useQueryClient();
  const [tid, setTid] = useState("");
  const location = useLocation();
  const profile = useQuery({
    queryKey: ["profile"],
    queryFn: () => request<Profile>("/v1/auth/me"),
    retry: false,
  });
  useEffect(() => {
    const expired = () => {
      forgetSession(qc);
    };
    window.addEventListener("kcs:session-expired", expired);
    return () => window.removeEventListener("kcs:session-expired", expired);
  }, [qc]);
  if (profile.isPending)
    return (
      <div className="loading">
        <Spin />
      </div>
    );
  if (
    profile.error &&
    !(profile.error instanceof ApiError && profile.error.status === 401)
  )
    return (
      <div className="boot-error">
        <Problem error={profile.error} />
        <Button onClick={() => profile.refetch()}>重試連線</Button>
      </div>
    );
  if (!profile.data) return <Login />;
  const tenant =
    profile.data.memberships.find((m) => m.tenant_id === tid) ||
    profile.data.memberships[0];
  if (!tenant)
    return (
      <div className="boot-error">
        <Alert type="warning" message="帳號尚未加入有效團隊，請聯絡管理員" />
        <Button
          onClick={async () => {
            await request("/v1/auth/logout", "POST", undefined, {
              csrf: profile.data!.csrf_token,
            });
            forgetSession(qc);
          }}
        >
          登出
        </Button>
      </div>
    );
  return (
    <Shell
      key={tenant.tenant_id}
      profile={profile.data}
      tenant={tenant}
      onTenant={setTid}
    />
  );
}
createRoot(document.getElementById("root")!).render(
  <ConfigProvider
    locale={zhTW}
    theme={{
      token: {
        colorPrimary: "#256b5e",
        borderRadius: 6,
        fontFamily: 'Inter, "Microsoft JhengHei", "PingFang TC", sans-serif',
        colorBgLayout: "#fbfcfa",
      },
    }}
  >
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </ConfigProvider>,
);
