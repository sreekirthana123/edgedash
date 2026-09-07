#!/usr/bin/env python3
from edgedash.config import Config
from edgedash.orchestrator import run_cycle

if __name__ == "__main__":
    config = Config.load("config.yaml")
    config.use_mock_fetcher = True
    config.score_batch_size = 2  # Only score 2 to test quickly
    run_cycle(config)
