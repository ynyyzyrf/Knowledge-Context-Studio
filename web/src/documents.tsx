import { useState } from "react";
import {
  Alert,
  Button,
  Card,
  Input,
  Modal,
  Space,
  Table,
  Typography,
} from "antd";
import { Load, Problem, Status, useData, useWrite, when } from "./shared";

type Document = {
  id: string;
  filename: string;
  byte_size: number;
  checksum: string;
  state: string;
  deleted: boolean;
  chunk_count: number;
  attempt: number;
  error_code?: string;
  created_at: number;
};
type Listing = { items: Document[]; can_edit: boolean; has_more: boolean };
type Detail = Document & {
  chunks: { number: number; page: number | null; content: string }[];
  has_more: boolean;
};
const errors: Record<string, string> = {
  document_invalid_pdf: "PDF 格式損壞或無法解析，請重新匯出文件。",
  document_encrypted_pdf: "不支援加密 PDF，請上傳未加密版本。",
  document_page_limit: "PDF 超過 100 頁上限。",
  document_text_limit: "解析文字超過 200,000 字元上限。",
  document_chunk_limit: "解析結果超過 100 個片段上限。",
  document_pdf_ocr_required:
    "PDF 包含無可擷取文字的頁面，請先 OCR 或移除空白頁後重新匯入。",
  document_requires_utf8: "文字文件需使用 UTF-8 編碼。",
  document_invalid_text: "文件含二進位或不支援的控制字元。",
  document_empty_text: "文件沒有可索引的文字。",
  document_parse_timeout: "解析超時，請縮小文件或重試。",
  document_processing_failed: "處理失敗，可重試；持續失敗請聯絡管理員。",
  engine_timeout: "引擎逾時，背景任務會依重試策略處理。",
  engine_unavailable: "引擎暫時無法使用，請檢查服務後重試。",
  engine_index_incomplete: "索引尚未完整，文件不會提供給 Agent。",
};

export function Documents({ spaceId }: { spaceId: string }) {
  const [offset, setOffset] = useState(0);
  const base = `/spaces/${spaceId}/documents`;
  const data = useData<Listing>(
    `${base}?limit=20&offset=${offset}`,
    true,
    (d) =>
      d?.items.some((x) => ["pending", "running", "retry"].includes(x.state)) ||
      false,
  );
  const write = useWrite();
  const [file, setFile] = useState<File>();
  const [inputKey, setInputKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [selected, setSelected] = useState<string>();
  const [removing, setRemoving] = useState<Document>();
  async function action(path: string, method: string, body?: unknown) {
    setBusy(true);
    setError(undefined);
    try {
      await write(path, method, body);
      return true;
    } catch (e) {
      setError(e);
      return false;
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card title="文件匯入">
      <Alert
        type="info"
        message="支援 .md、.txt 與文字型 PDF。每檔最多 10 MB、100 頁、200,000 字元；不支援掃描／加密 PDF。索引完成後，已授權的外部 Agent 才能檢索。"
      />
      {error ? <Problem error={error} /> : null}
      <Load query={data}>
        {data.data?.can_edit && (
          <Space
            direction="vertical"
            style={{ width: "100%", margin: "16px 0" }}
          >
            <Input
              key={inputKey}
              type="file"
              aria-label="選擇匯入文件"
              accept=".md,.txt,.pdf"
              disabled={busy}
              onChange={(e) => {
                setFile(e.target.files?.[0]);
                setError(undefined);
              }}
            />
            <Button
              type="primary"
              loading={busy}
              disabled={!file || file.size > 10 * 1024 * 1024 || !file.size}
              onClick={async () => {
                if (
                  file &&
                  (await action(
                    `${base}?filename=${encodeURIComponent(file.name)}`,
                    "POST",
                    file,
                  ))
                ) {
                  setFile(undefined);
                  setInputKey((x) => x + 1);
                  setOffset(0);
                }
              }}
            >
              上傳並建立索引
            </Button>
            {file && (file.size > 10 * 1024 * 1024 || !file.size) && (
              <Alert
                type="error"
                message="請選擇非空、且不超過 10 MB 的文件。"
              />
            )}
          </Space>
        )}
        <Table
          rowKey="id"
          size="small"
          pagination={false}
          scroll={{ x: 680 }}
          dataSource={data.data?.items}
          columns={[
            {
              title: "文件",
              dataIndex: "filename",
              render: (name, row) => (
                <>
                  <Button type="link" onClick={() => setSelected(row.id)}>
                    {name}
                  </Button>
                  <div>
                    {Math.ceil(row.byte_size / 1024)} KB · {row.chunk_count}{" "}
                    個片段
                  </div>
                </>
              ),
            },
            {
              title: "狀態",
              render: (_, row) => (
                <>
                  <Status value={row.deleted ? "deleted" : row.state} />
                  {row.deleted && (
                    <div>
                      引擎清理：
                      <Status value={row.state} />
                    </div>
                  )}
                  {row.error_code && (
                    <div className="muted">
                      {errors[row.error_code] || row.error_code}
                    </div>
                  )}
                </>
              ),
            },
            { title: "匯入時間", render: (_, row) => when(row.created_at) },
            {
              title: "操作",
              render: (_, row) =>
                data.data?.can_edit && (
                  <Space>
                    {row.state === "failed" && (
                      <Button
                        disabled={busy}
                        onClick={() =>
                          action(`${base}/${row.id}/retry`, "POST")
                        }
                      >
                        重試
                      </Button>
                    )}
                    {!row.deleted && (
                      <Button
                        danger
                        disabled={busy}
                        onClick={() => setRemoving(row)}
                      >
                        刪除
                      </Button>
                    )}
                  </Space>
                ),
            },
          ]}
        />
        <Space style={{ marginTop: 12 }}>
          <Button
            disabled={!offset}
            onClick={() => setOffset(Math.max(0, offset - 20))}
          >
            上一批文件
          </Button>
          <Button
            disabled={!data.data?.has_more}
            onClick={() => setOffset(offset + 20)}
          >
            下一批文件
          </Button>
          <Button onClick={() => data.refetch()}>重新載入文件</Button>
        </Space>
      </Load>
      <Modal
        title="刪除此文件？"
        open={!!removing}
        confirmLoading={busy}
        onCancel={() => setRemoving(undefined)}
        onOk={async () => {
          if (removing && (await action(`${base}/${removing.id}`, "DELETE")))
            setRemoving(undefined);
        }}
      >
        <p>{removing?.filename}</p>
        <p>
          原件與解析文字會移除，立即停止檢索；引擎內容由背景任務清理。需要恢復時請重新上傳原檔。
        </p>
      </Modal>
      {selected && (
        <DocumentPreview
          key={selected}
          base={base}
          id={selected}
          close={() => setSelected(undefined)}
        />
      )}
    </Card>
  );
}

function DocumentPreview({
  base,
  id,
  close,
}: {
  base: string;
  id: string;
  close: () => void;
}) {
  const [offset, setOffset] = useState(0);
  const data = useData<Detail>(`${base}/${id}?offset=${offset}`);
  return (
    <Modal
      open
      title={data.data?.filename || "文件來源"}
      footer={null}
      onCancel={close}
      width={760}
    >
      <Load query={data}>
        <p>不可編輯匯入版本 v1 · SHA-256</p>
        <Typography.Text copyable>{data.data?.checksum}</Typography.Text>
        {data.data?.deleted ? (
          <Alert type="info" message="文件已刪除，正文不再保留。" />
        ) : (
          data.data?.chunks.map((c) => (
            <div className="memory-reference" key={c.number}>
              <strong>
                片段 {c.number + 1}
                {c.page ? ` · 第 ${c.page} 頁` : ""}
              </strong>
              <p style={{ whiteSpace: "pre-wrap" }}>{c.content}</p>
            </div>
          ))
        )}
        <Space>
          <Button
            disabled={!offset}
            onClick={() => setOffset(Math.max(0, offset - 10))}
          >
            上一批片段
          </Button>
          <Button
            disabled={!data.data?.has_more}
            onClick={() => setOffset(offset + 10)}
          >
            下一批片段
          </Button>
        </Space>
      </Load>
    </Modal>
  );
}
