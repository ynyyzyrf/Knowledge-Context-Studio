import { useState } from "react";
import { Button, Input, Modal, Space, Tree } from "antd";
import {
  DownOutlined,
  FolderOutlined,
  FolderAddOutlined,
} from "@ant-design/icons";
import type { DataNode } from "antd/es/tree";
import { Load, Problem, useData, useWrite } from "./shared";

type Folder = { path: string; name: string };
export function FolderPicker({
  spaceId,
  scope,
  value,
  onChange,
  disabled,
}: {
  spaceId: string;
  scope: "private" | "shared";
  value: string;
  onChange: (path: string) => void;
  disabled?: boolean;
}) {
  const root = scope === "private" ? "user/default/resources" : "resources";
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(value);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const folders = useData<{ items: Folder[] }>(
    `/spaces/${spaceId}/folders?scope=${scope}`,
    open,
  );
  const write = useWrite();
  const children = (parent: string): DataNode[] =>
    (folders.data?.items || [])
      .filter((f) => f.path.split("/").slice(0, -1).join("/") === parent)
      .map((f) => ({
        key: f.path,
        title: f.name,
        icon: <FolderOutlined />,
        children: children(f.path),
      }));
  const create = async () => {
    setBusy(true);
    setError(undefined);
    try {
      const result = await write<Folder>(`/spaces/${spaceId}/folders`, "POST", {
        parent: selected,
        scope,
        name: name.trim(),
      });
      setSelected(result.path);
      setName("");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="upload-destination">
      <label>保存到目錄</label>
      <div className="destination-control">
        <FolderOutlined />
        <span title={`${root}/${value}`}>
          {root}/{value ? value + "/" : ""}
        </span>
        <Button
          disabled={disabled}
          onClick={() => {
            setSelected(value);
            setName("");
            setError(undefined);
            setOpen(true);
          }}
        >
          選擇目錄
        </Button>
      </div>
      <Modal
        title="選擇保存目錄"
        open={open}
        okText="確定"
        cancelText="取消"
        onCancel={() => {
          if (!busy) setOpen(false);
        }}
        onOk={() => {
          onChange(selected);
          setOpen(false);
        }}
        okButtonProps={{
          disabled: busy || folders.isPending || !!folders.error,
        }}
        cancelButtonProps={{ disabled: busy }}
        closable={!busy}
      >
        <p className="muted">
          {scope === "private"
            ? "目前登入使用者在此空間的私人知識資料。"
            : "此空間內供已授權 Agent 讀取的共享知識。"}
        </p>
        {error ? <Problem error={error} /> : null}
        <Load query={folders}>
          <Tree
            className="folder-picker-tree"
            blockNode
            showIcon
            showLine
            switcherIcon={<DownOutlined />}
            defaultExpandAll
            key={(folders.data?.items || []).map((f) => f.path).join("|")}
            selectedKeys={[selected]}
            treeData={[
              {
                key: "",
                title: root + "/",
                icon: <FolderOutlined />,
                children: children(""),
              },
            ]}
            onSelect={(keys) => {
              if (!busy && keys.length) setSelected(String(keys[0]));
            }}
          />
          <p className="folder-selection">
            已選：{root}/{selected ? selected + "/" : ""}
          </p>
          <Space.Compact style={{ width: "100%" }}>
            <Input
              aria-label="新資料夾名稱"
              placeholder="在所選目錄下建立資料夾"
              maxLength={80}
              value={name}
              disabled={busy}
              onChange={(e) => setName(e.target.value)}
              onPressEnter={() => {
                if (name.trim() && !busy) void create();
              }}
            />
            <Button
              icon={<FolderAddOutlined />}
              loading={busy}
              disabled={!name.trim()}
              onClick={create}
            >
              建立
            </Button>
          </Space.Compact>
          <p className="muted">建立後目錄會立即保存；取消只會放棄這次選擇。</p>
        </Load>
      </Modal>
    </div>
  );
}
