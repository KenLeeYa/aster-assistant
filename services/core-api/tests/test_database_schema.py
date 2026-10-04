from ky_jarvis_core.persistence.schema import REQUIRED_TABLES, metadata


def test_required_phase_tables_exist() -> None:
    assert set(REQUIRED_TABLES) == set(metadata.tables)


def test_secret_bearing_records_store_hashes_not_plaintext_values() -> None:
    pairing_columns = set(metadata.tables["device_pairing_sessions"].columns.keys())
    refresh_columns = set(metadata.tables["mobile_refresh_token_families"].columns.keys())
    realtime_columns = set(metadata.tables["realtime_client_secret_issuances"].columns.keys())

    assert "secret_hash" in pairing_columns
    assert "one_time_secret" not in pairing_columns
    assert "current_token_hash" in refresh_columns
    assert "refresh_token" not in refresh_columns
    assert "secret_hash" in realtime_columns
    assert "client_secret" not in realtime_columns
