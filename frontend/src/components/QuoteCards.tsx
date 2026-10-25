import { Card } from "antd";

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
        const changeText =
          item.change === null
            ? "-"
            : `${item.change > 0 ? "+" : ""}${item.change.toFixed(2)}`;
        return (
          <Card
            key={item.point_id}
            size="small"
            className="quote-card"
            title={
              <span className="quote-card-title">
                <span className="quote-category">{item.category}</span>
                {item.spec}
              </span>
            }
          >
            <div className="quote-price-row">
              <div className={`quote-price ${changeClass}`}>
                {item.price.toFixed(2)}
                <span className="unit"> 元/吨</span>
              </div>
              <span className={`quote-change ${changeClass}`}>{changeText}</span>
            </div>
            <div className="quote-meta">
              <span className="quote-region">{item.region}</span>
              <span className="quote-code">{item.code}</span>
            </div>
            <div className="quote-date">{item.quote_date}</div>
          </Card>
        );
      })}
    </div>
  );
}
