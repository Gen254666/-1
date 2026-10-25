from steel_core.db.seed import DEFAULT_APP_CONFIG


def test_default_config_has_thresholds_and_disclaimers() -> None:
    anomaly = DEFAULT_APP_CONFIG["anomaly"]
    assert anomaly["daily_change_pct"] == 2.0
    assert anomaly["consecutive_days"] == 3
    assert anomaly["inventory_deviation_pct"] == 30.0
    assert anomaly["low_stock_pieces"] == 10

    assert DEFAULT_APP_CONFIG["quote"]["tax_mode"] == "as_is"
    assert DEFAULT_APP_CONFIG["disclaimer"]["quote"]
    assert DEFAULT_APP_CONFIG["disclaimer"]["report"]
