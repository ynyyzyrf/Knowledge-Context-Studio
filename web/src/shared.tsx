import { createContext, useContext, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { ApiError, errorText, request } from "./api";
import type { Membership, Profile } from "./types";
export const Context = createContext<{
  profile: Profile;
  tenant: Membership;
  token: string;
  setToken: (x: string) => void;
}>(null!);
export const useWorkspace = () => useContext(Context);
export function useData<T>(
  suffix: string,
  enabled = true,
  poll: boolean | ((data: T | undefined) => boolean) = false,
) {
  const { tenant } = useWorkspace();
  return useQuery({
    queryKey: ["tenant", tenant.tenant_id, suffix],
    queryFn: ({ signal }) =>
      request<T>(`/v1/tenants/${tenant.tenant_id}${suffix}`, "GET", undefined, {
        signal,
      }),
    enabled,
    refetchInterval: (q) =>
      (typeof poll === "function" ? poll(q.state.data) : poll) ? 3000 : false,
    refetchIntervalInBackground: false,
    retry: false,
  });
}
export function useWrite() {
  const { profile, tenant } = useWorkspace();
  const qc = useQueryClient();
  return async <T,>(path: string, method: string, body?: unknown) => {
    const result = await request<T>(
      `/v1/tenants/${tenant.tenant_id}${path}`,
      method,
      body,
      { csrf: profile.csrf_token },
    );
    await qc.invalidateQueries({ queryKey: ["tenant", tenant.tenant_id] });
    return result;
  };
}
const labels: Record<string, string> = {
  pending: "待處理",
  ready: "已同步",
  failed: "失敗",
  running: "處理中",
  retry: "待重試",
  succeeded: "已完成",
  obsolete: "已取代",
  candidate: "待審核",
  approved: "已審核",
  rejected: "已拒絕",
  active: "有效",
  disabled: "已停用",
  deleted: "已刪除",
  superseded: "已取代",
  tenant_admin: "團隊管理員",
  editor: "編輯者",
  viewer: "檢視者",
};
export function Status({ value }: { value: string }) {
  return (
    <Tag
      color={
        ["active", "ready", "succeeded"].includes(value)
          ? "green"
          : ["failed", "deleted"].includes(value)
            ? "red"
            : ["pending", "retry", "candidate"].includes(value)
              ? "gold"
              : "default"
      }
    >
      {labels[value] || value}
    </Tag>
  );
}
const tone: Record<string, string> = {
  ready: "var(--ok)",
  succeeded: "var(--ok)",
  active: "var(--ok)",
  failed: "var(--bad)",
  deleted: "var(--bad)",
  pending: "var(--warn)",
  retry: "var(--warn)",
  candidate: "var(--warn)",
  running: "var(--warn)",
};
export function Dot({ value }: { value: string }) {
  return (
    <span className="status-dot">
      <i style={{ background: tone[value] || "#b6bfb8" }} />
      {labels[value] || value}
    </span>
  );
}
export const when = (value: number) =>
  new Date(value * 1000).toLocaleString("zh-TW");
export const ago = (value?: number | null) => {
  if (!value) return "—";
  const diff = Date.now() / 1000 - value;
  if (diff < 60) return "剛剛";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分鐘前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小時前`;
  if (diff < 172800) return "昨天";
  if (diff < 7 * 86400) return `${Math.floor(diff / 86400)} 天前`;
  return new Date(value * 1000).toLocaleDateString("zh-TW");
};
export const short = (value: string) => value.slice(0, 8);
export function Heading({
  title,
  note,
  extra,
}: {
  title: string;
  note: string;
  extra?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{note}</p>
      </div>
      {extra}
    </div>
  );
}
export function Problem({ error }: { error: unknown }) {
  return (
    <Alert
      type="error"
      showIcon
      message={errorText(error)}
      description={
        error instanceof ApiError && error.requestId
          ? `追蹤編號：${error.requestId}`
          : undefined
      }
    />
  );
}
export function Load({
  query,
  children,
}: {
  query: { isPending: boolean; error: unknown; refetch: () => unknown };
  children: ReactNode;
}) {
  if (query.isPending)
    return (
      <div className="loading">
        <Spin tip="載入中" />
      </div>
    );
  if (query.error)
    return (
      <Space direction="vertical">
        <Problem error={query.error} />
        <Button onClick={() => query.refetch()}>重新載入</Button>
      </Space>
    );
  return <>{children}</>;
}
export function Blank({ text = "尚無資料" }: { text?: string }) {
  return <Empty description={text} image={Empty.PRESENTED_IMAGE_SIMPLE} />;
}
export interface Field {
  name: string;
  label: string;
  type?: "password" | "textarea" | "number" | "select" | "multi";
  required?: boolean;
  min?: number;
  max?: number;
  options?: { label: string; value: string }[];
}
export interface FormSpec {
  title: string;
  note?: string;
  fields: Field[];
  values?: Record<string, unknown>;
  submit: (values: Record<string, unknown>) => Promise<unknown>;
  danger?: boolean;
  okText?: string;
}
export function ActionForm({
  spec,
  close,
}: {
  spec: FormSpec | null;
  close: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [form] = Form.useForm();
  if (!spec) return null;
  return (
    <Modal
      open
      title={spec.title}
      onCancel={() => {
        if (!busy) close();
      }}
      onOk={() => form.submit()}
      confirmLoading={busy}
      okText={spec.okText || "確認"}
      cancelText="取消"
      okButtonProps={{ danger: spec.danger }}
      maskClosable={!busy}
      destroyOnClose
    >
      {spec.note && <p className="muted">{spec.note}</p>}
      {error ? <Problem error={error} /> : null}
      <Form
        form={form}
        layout="vertical"
        initialValues={spec.values}
        onFinish={async (values) => {
          setBusy(true);
          setError(null);
          try {
            await spec.submit(values);
            close();
          } catch (e) {
            setError(e);
          } finally {
            setBusy(false);
          }
        }}
      >
        {spec.fields.map((f) => (
          <Form.Item
            key={f.name}
            name={f.name}
            label={f.label}
            rules={[
              { required: f.required !== false, message: `請填寫${f.label}` },
            ]}
          >
            {f.type === "textarea" ? (
              <Input.TextArea rows={4} maxLength={f.max} />
            ) : f.type === "password" ? (
              <Input.Password autoComplete="new-password" maxLength={f.max} />
            ) : f.type === "number" ? (
              <InputNumber min={f.min} max={f.max} style={{ width: "100%" }} />
            ) : f.type === "select" || f.type === "multi" ? (
              <Select
                mode={f.type === "multi" ? "multiple" : undefined}
                options={f.options}
              />
            ) : (
              <Input maxLength={f.max || 160} />
            )}
          </Form.Item>
        ))}
      </Form>
    </Modal>
  );
}
export function useForms() {
  const [spec, setSpec] = useState<FormSpec | null>(null);
  const [serial, setSerial] = useState(0);
  return {
    open: (x: FormSpec) => {
      setSerial((s) => s + 1);
      setSpec(x);
    },
    modal: <ActionForm key={serial} spec={spec} close={() => setSpec(null)} />,
  };
}
export function ID({ value }: { value: string }) {
  return (
    <Typography.Text className="id" title={value} copyable={{ text: value }}>
      {short(value)}
    </Typography.Text>
  );
}
