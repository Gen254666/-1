import { applyWatermark, escapeMarkdown, quoteToMarkdown } from "../utils/export";

test("escapes markdown control characters", () => {
  expect(escapeMarkdown("A*B_[C]")).toBe("A\\*B\\_\\[C\\]");
});

test("applies watermark at top and bottom", () => {
  const result = applyWatermark("# 报价单", "> 导出人：alice");
  expect(result.startsWith("> 导出人：alice")).toBe(true);
  expect(result.trimEnd().endsWith("> 导出人：alice")).toBe(true);
});

test("serializes quote to markdown with sources and disclaimer", () => {
  const markdown = quoteToMarkdown({
    lines: [
      {
        spec: "100*100*2.5*6m",
        unit_price: 3550,
        tax_add: 220,
        weight_per_piece: 24.93,
        pieces: 10,
        price_per_piece: 88.5,
        subtotal: 885,
        ton_price: 3550,
      },
    ],
    freight: 100,
    processing_fee: 50,
    total: 1035,
    total_weight: 0.2493,
    average_ton_price: 3550,
    tax_mode: "as_is",
    warnings: ["含税口径待确认"],
    sources: [{ type: "inventory", date: "2026-10-23", warehouse: "昆明宝象库" }],
    disclaimer: "本报价仅供参考。",
    valid_until: "2026-10-23",
  });

  expect(markdown).toContain("# 钢材报价单");
  expect(markdown).toContain("合计：1035.00 元");
  expect(markdown).toContain("含税口径待确认");
  expect(markdown).toContain("昆明宝象库");
  expect(markdown).toContain("本报价仅供参考。");
});
