import type { QuoteResult } from "../api/types";

export function escapeMarkdown(value: string): string {
  return value.replace(/([\\`*_{}\[\]|<>])/g, "\\$1");
}

export function applyWatermark(markdown: string, watermark: string): string {
  if (!watermark) return markdown;
  return `${watermark}\n\n${markdown.trimEnd()}\n\n${watermark}\n`;
}

export function quoteToMarkdown(quote: QuoteResult): string {
  const rows = quote.lines.map(
    (line) =>
      `| ${escapeMarkdown(line.spec)} | ${line.unit_price.toFixed(2)} | ${line.weight_per_piece.toFixed(3)} | ${line.pieces} | ${line.price_per_piece.toFixed(2)} | ${line.subtotal.toFixed(2)} |`,
  );
  const sources = quote.sources
    .map((source) => {
      const parts = Object.entries(source)
        .filter(([, value]) => value !== null && value !== undefined && value !== "")
        .map(([key, value]) => `${escapeMarkdown(key)}: ${escapeMarkdown(String(value))}`);
      return `- ${parts.join("，")}`;
    })
    .join("\n");

  return [
    "# 钢材报价单",
    "",
    `有效期：${quote.valid_until}`,
    "",
    "| 规格 | 单价 | 支重 | 数量 | 支售价 | 小计 |",
    "|---|---|---|---|---|---|",
    ...rows,
    "",
    `合计：${quote.total.toFixed(2)} 元`,
    `总重量：${quote.total_weight.toFixed(4)} 吨`,
    `运费：${quote.freight.toFixed(2)} 元；加工费：${quote.processing_fee.toFixed(2)} 元`,
    `含税口径：${quote.tax_mode}`,
    "",
    "## 数据来源",
    sources || "无",
    "",
    "## 风险提示",
    ...(quote.warnings.length
      ? quote.warnings.map((warning) => `- ${escapeMarkdown(warning)}`)
      : ["- 无"]),
    "",
    `> ${escapeMarkdown(quote.disclaimer)}`,
    "",
  ].join("\n");
}

export function downloadText(filename: string, text: string): void {
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
