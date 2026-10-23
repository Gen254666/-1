from steel_core.db.seed import DEFAULT_APP_CONFIG, PUBLIC_POINTS

REQUIRED_FIELDS = {"code", "category", "spec", "region", "source", "unit"}


def test_public_points_are_16_and_unique() -> None:
    assert len(PUBLIC_POINTS) == 16

    codes = [point["code"] for point in PUBLIC_POINTS]
    assert len(set(codes)) == 16


def test_public_points_have_required_fields() -> None:
    for point in PUBLIC_POINTS:
        assert REQUIRED_FIELDS <= set(point)
        assert point["source"] == "mysteel"
        assert point["unit"] == "元/吨"


def test_public_points_cover_business_categories() -> None:
    categories = {point["category"] for point in PUBLIC_POINTS}

    assert {
        "方管",
        "矩管",
        "圆管",
        "镀锌管",
        "角钢",
        "槽钢",
        "H型钢",
        "中厚板",
        "热卷",
        "高线",
        "盘螺",
        "螺纹钢",
    } <= categories


def test_default_config_has_thresholds_and_disclaimers() -> None:
    anomaly = DEFAULT_APP_CONFIG["anomaly"]
    assert anomaly["daily_change_pct"] == 2.0
    assert anomaly["consecutive_days"] == 3
    assert anomaly["inventory_deviation_pct"] == 30.0
    assert anomaly["low_stock_pieces"] == 10

    assert DEFAULT_APP_CONFIG["quote"]["tax_mode"] == "as_is"
    assert DEFAULT_APP_CONFIG["disclaimer"]["quote"]
    assert DEFAULT_APP_CONFIG["disclaimer"]["report"]
