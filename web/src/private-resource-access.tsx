import { useState } from "react";
import { Switch } from "antd";
import { Load, Problem, useData, useWrite } from "./shared";

export function PrivateResourceAccess({ spaceId }: { spaceId: string }) {
  const base = `/spaces/${spaceId}/user/default/agent-access`;
  const data = useData<{
    items: { agent_id: string; name: string; active: boolean }[];
  }>(base);
  const write = useWrite();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  return (
    <section aria-label="私人知識 Agent 授權">
      <h4>私人知識 Agent 授權</h4>
      <p className="muted">
        只授權此空間內你的私人 resources。Agent 需使用由你簽發的新 Token；舊
        Token 不會自動取得私人存取權。
      </p>
      {error ? <Problem error={error} /> : null}
      <Load query={data}>
        {data.data?.items.map((a) => (
          <p key={a.agent_id}>
            <Switch
              aria-label={`授權 ${a.name} 讀取私人知識`}
              checked={a.active}
              disabled={busy}
              onChange={async (active) => {
                setBusy(true);
                setError(undefined);
                try {
                  await write(`${base}/${a.agent_id}`, "PUT", { active });
                } catch (e) {
                  setError(e);
                } finally {
                  setBusy(false);
                }
              }}
            />{" "}
            {a.name}
          </p>
        ))}
        {!data.data?.items.length && (
          <p className="muted">此空間尚無可授權的 Agent。</p>
        )}
      </Load>
    </section>
  );
}
