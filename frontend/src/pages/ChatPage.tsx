import { SendOutlined } from "@ant-design/icons";
import { Button, Card, Input, Space, Typography, message as toast } from "antd";
import { useRef, useState } from "react";

import { streamChat } from "../api/client";
import type { Artifact } from "../api/types";
import { ArtifactRenderer } from "../components/ArtifactRenderer";

interface UiMessage {
  role: "user" | "assistant";
  content: string;
  artifacts: Artifact[];
}

export function ChatPage() {
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const updateAssistant = (updater: (current: UiMessage) => UiMessage) => {
    setMessages((previous) => {
      const copy = [...previous];
      const last = copy[copy.length - 1];
      if (last && last.role === "assistant") {
        copy[copy.length - 1] = updater(last);
      }
      return copy;
    });
    requestAnimationFrame(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }));
  };

  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setLoading(true);
    setMessages((previous) => [
      ...previous,
      { role: "user", content: text, artifacts: [] },
      { role: "assistant", content: "", artifacts: [] },
    ]);

    try {
      await streamChat(text, sessionId, {
        onEvent: (event, data) => {
          if (event === "session") {
            setSessionId(data.session_id);
          } else if (event === "artifact") {
            updateAssistant((current) => ({
              ...current,
              artifacts: [...current.artifacts, data as Artifact],
            }));
          } else if (event === "token") {
            updateAssistant((current) => ({
              ...current,
              content: current.content + (data.text ?? ""),
            }));
          } else if (event === "warning") {
            updateAssistant((current) => ({
              ...current,
              content: current.content + `\n\n提示：${data.message}`,
            }));
          } else if (event === "error") {
            updateAssistant((current) => ({
              ...current,
              content: current.content + `\n\n${data.message}`,
            }));
          } else if (event === "done") {
            setLoading(false);
          }
        },
      });
    } catch (error) {
      toast.error((error as Error).message);
      setLoading(false);
    }
  };

  return (
    <div className="chat-layout">
      <Card className="chat-card" bodyStyle={{ padding: 0 }}>
        <div className="chat-messages">
          {messages.length === 0 ? (
            <Typography.Paragraph type="secondary">
              试试问："今天昆明方管多少钱？" 或 "热卷昆明和成都价差多少？"
            </Typography.Paragraph>
          ) : null}
          {messages.map((item, index) => (
            <div key={index} className={`chat-message chat-${item.role}`}>
              <div className="chat-bubble">{item.content || (loading ? "..." : "")}</div>
              {item.artifacts.map((artifact, artifactIndex) => (
                <div key={artifactIndex} className="chat-artifact">
                  <ArtifactRenderer artifact={artifact} />
                </div>
              ))}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
        <div className="chat-input">
          <Space.Compact style={{ width: "100%" }}>
            <Input.TextArea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="输入行情问题..."
              autoSize={{ minRows: 1, maxRows: 4 }}
              onPressEnter={(event) => {
                if (!event.shiftKey) {
                  event.preventDefault();
                  void send();
                }
              }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={loading}
              onClick={() => void send()}
            >
              发送
            </Button>
          </Space.Compact>
        </div>
      </Card>
    </div>
  );
}
