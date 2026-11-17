import sys
from pathlib import Path

# Ensure project root is on sys.path when running as a script
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from insider_platform.config import load_config
from insider_platform.db import connect, init_db, upsert_app_config


def main() -> None:
    cfg = load_config()
    init_db(cfg.DB_DSN)
    with connect(cfg.DB_DSN) as conn:
        upsert_app_config(conn, "current_parse_version", cfg.CURRENT_PARSE_VERSION)
        upsert_app_config(conn, "owner_norm_version", cfg.OWNER_NORM_VERSION)
        upsert_app_config(conn, "current_cluster_version", cfg.CURRENT_CLUSTER_VERSION)
        upsert_app_config(conn, "current_trend_version", cfg.CURRENT_TREND_VERSION)
        upsert_app_config(conn, "current_outcomes_version", cfg.CURRENT_OUTCOMES_VERSION)
        upsert_app_config(conn, "current_stats_version", cfg.CURRENT_STATS_VERSION)
        upsert_app_config(conn, "current_market_cap_version", cfg.CURRENT_MARKET_CAP_VERSION)
        upsert_app_config(conn, "ai_input_schema_version", cfg.AI_INPUT_SCHEMA_VERSION)
        upsert_app_config(conn, "ai_output_schema_version", cfg.AI_OUTPUT_SCHEMA_VERSION)
        upsert_app_config(conn, "prompt_version", cfg.PROMPT_VERSION)

    print(f"DB initialized: {cfg.DB_DSN}")


if __name__ == "__main__":
    main()
