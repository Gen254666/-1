import { Card, Tag } from "antd";

import type { QuoteItem } from "../api/types";

export function QuoteCards({ items }: { items: QuoteItem[] }) {
  if (!items.length) return <Card>暂无报价</Card>;

  return (
    <div className="card-grid">
      {items.map((item) => {
        const changeClass =
          item.change === null || item.change === 0
            ? "price-flat"
            : item.change > 0
              ? "price-up"
              : "price-down";
        return (
          <Card key={item.point_id} size="small" title={`${item.category} ${item.spec}`}>
            <div className={`quote-price ${changeClass}`}>
              {item.price.toFixed(2)}
              <span className="unit"> 元/吨</span>
            </div>
            <div className="quote-meta">
              <Tag>{item.region}</Tag>
              <span>{item.code}</span>
            </div>
            <div className={changeClass}>
              涨跌：{item.change === null ? "-" : item.change.toFixed(2)}
            </div>
            <div className="quote-date">{item.quote_date}</div>
          </Card>
        );
      })}
    </div>
  );
}
