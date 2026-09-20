# Enterprise-Grade Trailing Stop Engine & Samurai AI Reverse Engineering

## Goal
Build a strict, modular, and enterprise-grade trailing-stop engine and a Samurai AI OG reverse-engineering system, completely separated from broker API implementations. The project will incorporate and refactor the previously analyzed files (`config.py`, `data_fetcher.py`, `optimize_exits.py`, `order_executor.py`, `position_manager.py`) into the new clean architecture.

> [!WARNING]
> **Data Dependency:** The master prompt requires analyzing `/mnt/data/statement.csv` as the First Execution Requirement. If this file is not available in the environment, we will need it to proceed with the forensic analysis phases.

## Open Questions

1. **`statement.csv` Location:** Is the historical trade statement file available locally? (I am currently searching the filesystem for it). If not, could you provide it?
2. **Existing Files Refactoring:** The master prompt mandates the use of Pydantic, SQLAlchemy, and a strict separation of concerns. Are you okay with heavily refactoring the `order_executor.py` and `position_manager.py` to fit into the new `BrokerAdapter` and `StateStore` interfaces, respectively?

## Implementation Phases (Strictly following the Master Prompt)

### Phase 1: Project Setup & Domain Models
- Initialize the directory structure (`trading_engine/src/trading_engine/...`).
- Setup `pyproject.toml` with dependencies (`pydantic`, `sqlalchemy`, `pandas`, `httpx`, `structlog`, etc.).
- Implement Core Domain Models (`Position`, `Order`, `MarketState`, `TrailingDecision`) in `src/trading_engine/models/`.

### Phase 2: Engine & Validation Core
- Implement the `TrailingPolicy` abstract base class.
- Implement the universal stop validation logic (ensuring stops never worsen protection, tick size normalization, etc.) in `src/trading_engine/core/validation.py`.
- Build the core engine loop (`src/trading_engine/core/engine.py`).

### Phase 3: Generic Trailing Policies
- Implement basic policies: Fixed Distance, Percentage, Break-even, Step Trailing, ATR Trailing, Chandelier Exit.

### Phase 4: Broker Abstraction & Refactoring Legacy Code
- Define the abstract `BrokerAdapter`.
- Implement the `SimulatorBroker` for safe initial testing.
- **Refactor `order_executor.py` and `data_fetcher.py`** into a `BinanceFuturesAdapter` implementing the `BrokerAdapter` interface, hiding all HTTP/HMAC logic behind the abstraction.
- **Refactor `config.py`** into `src/trading_engine/config/settings.py` using `pydantic-settings`.
- **Refactor `position_manager.py`** into a persistent repository in `src/trading_engine/persistence/state_store.py` (starting with SQLite/JSON).

### Phase 5: Observability & Notifications
- Implement JSON structured logging using `structlog`.
- Build the event/audit system to track every decision and stop modification.
- Implement the `NotificationProvider` with a Telegram adapter (reusing logic from your previous setups if applicable).

### Phase 6: Samurai Research & Forensics
- Implement `SamuraiTradeLoader` and `SamuraiTradeCleaner`.
- Ingest `statement.csv` and generate the data-quality report (`reports/samurai_forensics.md`).
- **Refactor `optimize_exits.py`** into the `research/samurai/` module to assist in candidate model generation.

### Phase 7: Replay & Validation
- Implement the historical event-driven replay engine.
- Test candidate policies against the observed trades.
- Freeze the best replica policy (`SamuraiTrailingPolicy`).

## Verification Plan
- Unit tests for all policies and validation logic.
- Integration tests using the `SimulatorBroker`.
- Running the `simulate-trailing` CLI command in `--dry-run` mode.
- Generating the final `samurai_forensics.md` report showing Replica vs. Observed behavior.


The short answer is almost, but there are two critical components you need to wire up before you put real money on the line.

What we have built so far is the Core Logic & Decision Engine. It is structurally ready and your BinanceFuturesAdapter is fully capable of securely signing and firing the API requests.

However, before deploying it live with your Binance keys, we need to address these two things:

1. The Live Data Feed (WebSockets)
Right now, our core/engine.py has a process_tick(market: MarketState) function that expects to be fed live market prices. In Phase 7, we used the ReplayEngine to feed it synthetic historical ticks. For a live deployment, you will need a main.py entry point that connects to the Binance Futures WebSocket Stream. As price updates flow in from the WebSocket, the script will parse them into MarketState objects and feed them directly into the engine's process_tick() function.

2. Entry Signals vs. Exit Management
This engine is a dedicated Trailing Stop Engine. It assumes that a position is already open (either because you opened it manually, or a separate TradingView webhook triggered an entry). If you want the engine to automatically open positions as well, you will need to implement an entry strategy or webhook listener to trigger the broker.open_position() logic before the trailing engine takes over.

Recommendation:
Before configuring real Binance keys, you should configure your Binance Testnet keys in the .env file (binance_testnet=True). We can quickly write a main.py script that hooks up the Binance WebSocket, open a test position manually, and watch the engine perfectly trail the stop loss in real-time on the Testnet.

Would you like to build that WebSocket connection script next so we can run a live Testnet deployment?