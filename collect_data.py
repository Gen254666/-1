import httpx, json
from datetime import date, timedelta

BASE = 'http://127.0.0.1:8000'

print("=" * 55)
print("   钢材行情智能体 · 数据采集（用于简历素材）")
print("=" * 55)

# 登录
r = httpx.post(f'{BASE}/api/auth/login',
               json={'username': 'admin', 'password': 'Steel@2026'}, timeout=15)
h = {'Authorization': f'Bearer {r.json()["access_token"]}'}
print("[1] 登录成功")

# 看板
d = httpx.get(f'{BASE}/api/dashboard', headers=h, timeout=15).json()
print(f"[2] 看板数据: 日期={d['date']} 报价={d['quotes']['total']}条 库存={d['inventory']['total']}条 异常={len(d['anomalies'])}条")

# 报价单
spec = d['inventory']['items'][0]['spec']
q = httpx.post(f'{BASE}/api/quote/generate', headers=h,
               json={'spec': spec, 'pieces': 100, 'freight': '50', 'processing_fee': '10'},
               timeout=15).json()
print(f"[3] 报价单: {spec} x 100支, 合计 ¥{q['total']}")

# 点位总数
p = httpx.get(f'{BASE}/api/points?page=1&page_size=100', headers=h, timeout=15).json()
total_points = p.get('total', 0)
public = sum(1 for i in p.get('items', []) if i.get('owner_type') == 'public')
print(f"[4] 点位配置: 共{total_points}个, 公共点位{public}个")

# 健康检查
h1 = httpx.get(f'{BASE}/healthz', timeout=5).json()
h2 = httpx.get('http://127.0.0.1:8001/healthz', timeout=5).json()
print(f"[5] 服务健康: Agent={h1['status']} MCP={h2['status']}")

# 列前10个报价品种
print("\n[6] 覆盖品种（前10）:")
for it in d['quotes']['items'][:10]:
    print(f"    {it['category']} | {it['spec']} | {it['region']} | ¥{it['price']}")

print("\n" + "=" * 55)
