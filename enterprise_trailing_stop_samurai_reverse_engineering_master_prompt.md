# Enterprise-Grade Trading Trailing-Stop Engine + Samurai AI OG Reverse Engineering

This document is the master implementation prompt for building a production-quality,
reusable trailing-stop engine and a separate Samurai AI OG reverse-engineering system.

## Objectives

Build two strictly separated systems:

1. **Generic Trailing Stop Engine**
   - Broker-agnostic
   - Strategy-agnostic
   - Reusable across XAUUSD, Forex, NIFTY, US stocks, crypto, etc.
   - Suitable for backtesting, paper trading, and future live trading
   - No API credentials inside the engine

2. **Samurai AI OG Reverse Engineering**
   - Infer entry behavior
   - Infer initial SL behavior
   - Infer TP behavior
   - Infer break-even behavior
   - Infer trailing activation
   - Infer trailing distance and step
   - Infer exit and position-management behavior
   - Validate hypotheses against historical observations
   - Never hard-code assumptions without evidence

Raw dataset:

`/mnt/data/statement.csv`

Treat the raw dataset as immutable evidence.

---

## Research Principle

Always distinguish:

- OBSERVED FACT
- HYPOTHESIS
- INFERRED RULE
- VALIDATED RULE
- UNCONFIRMED ASSUMPTION

Do not assume the public description of Samurai AI OG is its exact algorithm.

Do not prematurely optimize.

The first objective is faithful reconstruction, not profitability optimization.

---

# Architecture

```text
Strategy
   |
   v
Signal
   |
   v
Order
   |
   v
Trailing Stop Engine
   |
   v
Trailing Policy
   |
   v
Trailing Decision
   |
   v
Broker Adapter
   |
   v
Broker/API
```

The trailing engine must never contain broker-specific API calls.

## Recommended repository

```text
trading_engine/
├── pyproject.toml
├── README.md
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
│
├── src/trading_engine/
│   ├── core/
│   │   ├── engine.py
│   │   ├── state_machine.py
│   │   ├── decision.py
│   │   ├── validation.py
│   │   ├── exceptions.py
│   │   └── clock.py
│   │
│   ├── models/
│   │   ├── order.py
│   │   ├── position.py
│   │   ├── market.py
│   │   ├── symbol.py
│   │   ├── stop.py
│   │   └── enums.py
│   │
│   ├── policies/
│   │   ├── base.py
│   │   ├── fixed_distance.py
│   │   ├── breakeven.py
│   │   ├── step.py
│   │   ├── percentage.py
│   │   ├── atr.py
│   │   ├── swing.py
│   │   ├── chandelier.py
│   │   └── samurai.py
│   │
│   ├── brokers/
│   │   ├── base.py
│   │   ├── simulator.py
│   │   └── adapters/
│   │
│   ├── execution/
│   │   ├── executor.py
│   │   ├── retry.py
│   │   └── idempotency.py
│   │
│   ├── persistence/
│   │   ├── state_store.py
│   │   ├── event_store.py
│   │   └── repositories.py
│   │
│   ├── observability/
│   │   ├── logging.py
│   │   ├── events.py
│   │   ├── metrics.py
│   │   ├── alerts.py
│   │   └── correlation.py
│   │
│   ├── research/samurai/
│   │   ├── loader.py
│   │   ├── cleaner.py
│   │   ├── feature_engineering.py
│   │   ├── fingerprint.py
│   │   ├── hypotheses.py
│   │   ├── matcher.py
│   │   ├── replay.py
│   │   └── report.py
│   │
│   ├── backtesting/
│   │   ├── engine.py
│   │   ├── simulator.py
│   │   ├── fills.py
│   │   └── performance.py
│   │
│   └── config/
│       ├── settings.py
│       └── schemas.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── regression/
│   ├── property/
│   └── fixtures/
│
├── data/
│   ├── raw/
│   ├── processed/
│   ├── features/
│   └── reports/
│
├── logs/
├── scripts/
└── docs/
```

---

# Technology

Use Python 3.12+ with:

- pydantic
- pydantic-settings
- pandas
- numpy
- scipy where useful
- pytest
- hypothesis
- structlog or equivalent structured logger
- tenacity
- SQLAlchemy
- SQLite initially, PostgreSQL-ready
- httpx
- prometheus-client
- YAML/TOML configuration

Use type hints throughout.

Use `Decimal` where exact price/monetary arithmetic matters.

---

# Domain Models

## Position / Order

Include at minimum:

```text
order_id
position_id
symbol
side
quantity
entry_price
current_price
current_stop_loss
take_profit
initial_stop_loss
initial_risk
activation_price
highest_price_since_entry
lowest_price_since_entry
realized_pnl
unrealized_pnl
opened_at
updated_at
broker
account_id_hash
metadata
```

Never store API credentials in domain objects.

## MarketState

Include:

```text
symbol
bid
ask
last
spread
timestamp
tick_size
point_size
min_stop_distance
volatility
ATR values if available
session
market_status
```

Keep the model extensible for OHLC, volume, VWAP, swing points, and order-book data.

---

# Trailing Policy Contract

Define an abstract policy similar to:

```python
class TrailingPolicy:
    def evaluate(
        self,
        position: Position,
        market: MarketState,
        state: TrailingState,
    ) -> TrailingDecision:
        ...
```

Policies calculate decisions only. They never modify broker orders.

## TrailingDecision

Actions:

```text
NO_ACTION
ACTIVATE
MOVE_STOP
MOVE_TO_BREAKEVEN
CLOSE_POSITION
REJECT
ERROR
```

Include:

```text
action
proposed_stop
previous_stop
reason_code
reason_message
trigger_price
profit
profit_r
timestamp
policy_name
policy_version
calculation_metadata
```

Example:

```python
TrailingDecision(
    action="MOVE_STOP",
    proposed_stop=4321.50,
    previous_stop=4318.20,
    reason_code="TRAILING_STEP_REACHED",
    reason_message="Price advanced enough to move the protective stop.",
    profit_r=1.73,
    policy_name="samurai_candidate_v03",
    policy_version="0.3.0",
)
```

---

# Universal Stop Rule

By default, a trailing stop must never worsen protection.

For BUY:

```text
new_stop >= old_stop
```

For SELL:

```text
new_stop <= old_stop
```

Reject regressions unless an explicit policy overrides the rule.

---

# Stop Validation

Before any broker modification:

1. Validate side
2. Validate symbol
3. Validate price
4. Normalize tick size
5. Validate minimum stop distance
6. Validate correct stop side
7. Validate improvement over current stop
8. Validate position still exists
9. Validate timestamp freshness
10. Validate no duplicate modification
11. Validate broker constraints

Every rejection needs a machine-readable reason code.

---

# Price Normalization

Implement instrument-aware:

```text
normalize_price()
```

using:

```text
tick_size
decimal_precision
```

Do not assume XAUUSD, NIFTY, AAPL, and BTCUSD have identical tick structures.

---

# Initial Risk and R-Multiple

Calculate:

```text
initial_risk = abs(entry_price - initial_stop_loss)
```

and:

```text
profit_R = current_profit_distance / initial_risk
```

Use R-multiples for activation, break-even, trailing, risk reporting, and analytics.

---

# Generic Trailing Policies

Implement independently.

## Fixed Distance

BUY:

```text
stop = price - distance
```

SELL:

```text
stop = price + distance
```

## Percentage

BUY:

```text
stop = price * (1 - percentage)
```

SELL:

```text
stop = price * (1 + percentage)
```

## Break-even

After configurable `activation_R`:

BUY:

```text
stop = entry + buffer
```

SELL:

```text
stop = entry - buffer
```

## Step Trailing

Parameters:

```text
activation_distance
trailing_distance
step_size
```

Only modify when the improvement reaches the configured step.

## ATR Trailing

Parameters:

```text
atr_period
atr_multiplier
activation_R
```

BUY:

```text
stop = price - ATR * multiplier
```

SELL:

```text
stop = price + ATR * multiplier
```

## Swing Trailing

BUY follows confirmed swing lows.

SELL follows confirmed swing highs.

Never use future candles in backtesting.

## Chandelier Exit

Implement a standard configurable Chandelier policy.

---

# Samurai Policy

Create:

```text
SamuraiTrailingPolicy
```

Initially leave it as research-required / not implemented.

Do not invent formulas.

Version candidates:

```text
samurai_candidate_v001
samurai_candidate_v002
samurai_candidate_v003
...
```

Every version must be reproducible.

---

# Samurai Data Ingestion

Load:

```text
/mnt/data/statement.csv
```

Treat it as immutable.

Create processed copies under:

```text
data/raw/
data/processed/
data/features/
data/reports/
```

Implement:

```text
SamuraiTradeLoader
SamuraiTradeCleaner
```

Detect:

- columns
- timestamp format
- timezone
- symbol
- direction
- entry
- exit
- SL
- TP
- pips
- profit
- duration

Never silently discard malformed records.

Log every discarded record with:

```text
record_id
reason
original values
timestamp
```

---

# Data Quality

Generate a data-quality report containing:

```text
total_records
valid_records
invalid_records
duplicate_records
missing_fields
impossible_prices
suspicious_records
timezone
symbol distribution
buy/sell distribution
```

Detect anomalous records automatically.

Preserve anomalies as `ANOMALOUS`; do not simply delete evidence.

---

# Samurai Forensic Analysis

For each valid trade calculate:

```text
entry_to_exit_distance
entry_to_sl_distance
entry_to_tp_distance
final_stop_distance
R_multiple
holding_seconds
holding_minutes
hour
day_of_week
session
winner_or_loser
maximum_known_profit
stop_behavior
```

Produce:

- distributions
- histograms
- quantiles
- clusters
- frequency tables
- correlations
- outlier analysis

---

# Initial SL Analysis

Do not assume the exported SL is the original stop.

Compare:

```text
entry -> SL
entry -> exit
entry -> TP
```

Look for evidence of:

- fixed initial risk
- dynamic stop
- trailing
- break-even
- tightening
- stop movement into profit

Generate:

```text
stop_loss_forensics.md
```

---

# TP Analysis

Calculate TP distance from entry.

Determine:

- fixed TP clusters
- variable TP clusters
- direction symmetry
- instrument dependence

Do not declare a rule without statistical support.

---

# Trailing Stop Forensics

For every winning trade, determine as far as the available data permits:

```text
entry
initial-risk hypothesis
maximum favorable excursion
final stop
exit
theoretical trailing distance
theoretical activation threshold
```

Compare candidate models:

```text
FixedDistance
FixedPercentage
RBased
ATR
Step
BreakevenThenTrail
Swing
Hybrid
```

---

# Historical Market Data Interface

Create:

```text
MarketDataProvider
```

Methods:

```text
get_ticks()
get_bars()
get_quote()
get_ohlc()
```

Support:

- CSV
- Parquet
- database
- future broker APIs

Keep historical data separate from strategy logic.

---

# Event-Driven Backtesting

The final validation must be event-driven, not just vectorized.

Events:

```text
MARKET_TICK
BAR_CLOSE
ORDER_OPENED
STOP_MODIFIED
TAKE_PROFIT
STOP_HIT
POSITION_CLOSED
```

Process chronologically.

No look-ahead bias.

---

# Exact Replay

For every Samurai trade:

1. Load historical market data around the timestamp.
2. Replay chronologically.
3. Run candidate entry logic.
4. Run candidate trailing policy.
5. Generate simulated orders.
6. Compare against observed trade.

Calculate:

```text
direction_match
timestamp_difference
entry_price_difference
SL_difference
TP_difference
exit_price_difference
duration_difference
```

---

# Replication Metrics

Do not reduce everything to one arbitrary score.

Report independently:

```text
direction_match_rate
entry_event_match_rate
entry_price_match_rate
initial_SL_match_rate
TP_match_rate
trailing_behavior_match_rate
exit_match_rate
```

Also report exact mismatches.

Example:

```text
Trade 87

Observed:
    SELL
    Entry: 4321.50
    Exit: 4318.20

Replica:
    SELL
    Entry: 4321.47
    Exit: 4318.11

Differences:
    Entry: -0.03
    Exit: -0.09
```

---

# No Look-Ahead Bias

At time T, only information available at or before T may be used.

Never use:

- future candles
- future highs/lows
- future volume
- future ATR
- future swing points
- future trades

The backtest engine should enforce chronological access.

---

# Trailing Engine State

Persist:

```text
position_id
activation_state
activation_timestamp
initial_risk
highest_price
lowest_price
current_stop
last_stop_update
last_stop_update_timestamp
policy_version
```

State must survive restart.

---

# Idempotency

Every broker modification needs an idempotency key based on:

```text
position_id
proposed_stop
policy_version
state_version
```

Duplicate submissions must be recognized.

---

# Broker Abstraction

Define:

```text
BrokerAdapter
```

with:

```text
get_position()
get_positions()
get_quote()
modify_stop()
close_position()
health_check()
```

Use `SimulatorBroker` first.

Live broker integrations come later.

---

# Security

Never put API keys in:

- source code
- logs
- CSV files
- exceptions
- database records
- Git
- Docker images
- notebooks

Use environment variables or a secrets manager.

`.env.example` may contain placeholders:

```text
BROKER_API_KEY=
BROKER_API_SECRET=
BROKER_ACCOUNT_ID=
```

Redact secrets from logs automatically.

---

# Enterprise Logging

Use structured JSON logging.

Every important event should include:

```text
timestamp
level
service
environment
component
event
correlation_id
position_id
order_id
symbol
side
policy
policy_version
message
```

Example:

```json
{
  "timestamp": "...",
  "level": "INFO",
  "component": "trailing_engine",
  "event": "STOP_MOVE",
  "position_id": "12345",
  "symbol": "XAUUSD",
  "side": "BUY",
  "old_stop": 4310.20,
  "new_stop": 4312.40,
  "price": 4315.10,
  "profit_r": 1.52,
  "reason": "TRAILING_STEP_REACHED"
}
```

---

# Human-Readable Logs

Also support readable console logs:

```text
13:42:11 INFO  XAUUSD BUY
Entry 4300.00 | Price 4312.50 | +1.25R

TRAILING ACTIVATED
Initial SL: 4290.00
New SL:     4300.20
Reason:     1.0R activation

13:42:14 INFO
STOP MOVED
4300.20 -> 4303.50
Reason: trailing step reached
```

A human must be able to understand what the engine is doing.

---

# Log Levels

Support:

```text
TRACE
DEBUG
INFO
WARNING
ERROR
CRITICAL
```

Defaults:

```text
production = INFO
research = DEBUG
forensic = TRACE
```

---

# Event Codes

Standardize codes such as:

```text
POSITION_OPENED
POSITION_UPDATED
POSITION_CLOSED

TRAILING_INACTIVE
TRAILING_ACTIVATED
BREAKEVEN_TRIGGERED
STOP_CANDIDATE_CREATED
STOP_REJECTED
STOP_MOVE_REQUESTED
STOP_MOVE_ACCEPTED
STOP_MOVE_FAILED

BROKER_REQUEST
BROKER_RESPONSE
BROKER_RETRY
BROKER_TIMEOUT

DATA_ERROR
STATE_RECOVERED
DUPLICATE_REQUEST
SAFETY_BLOCK
```

Every event must be searchable.

---

# Notifications

Create:

```text
NotificationProvider
```

Methods:

```text
send_info()
send_warning()
send_error()
send_critical()
```

Initial adapters:

- Console
- Telegram
- Email
- Webhook

Keep providers optional.

---

# Telegram Notifications

Example:

```text
🟢 TRAILING ACTIVATED

XAUUSD BUY
Entry: 4300.00
Price: 4310.80
Initial SL: 4290.00
New SL: 4300.20
Profit: +1.08R
```

Stop movement:

```text
🟡 STOP MOVED

XAUUSD BUY
4300.20 -> 4303.40
Price: 4313.80
Reason: STEP_REACHED
```

Error:

```text
🔴 BROKER ERROR

XAUUSD BUY
Stop update failed
Position: 12345
Retry: 2/5
```

Critical:

```text
🚨 SAFETY ALERT

Stop modification repeatedly rejected.
Manual intervention required.
```

Never send secrets.

---

# Notification Throttling

Never notify on every tick.

Notify on meaningful events:

- activation
- stop movement
- broker failure
- position closure
- repeated failure
- safety violation

---

# Metrics

Expose:

```text
positions_active
stop_updates_total
stop_update_failures
broker_latency
broker_errors
trailing_activations
trailing_rejections
notification_failures
engine_errors
```

Provide Prometheus-compatible metrics for live operation.

---

# Health Checks

Implement:

```text
/health
/ready
/metrics
```

or equivalent.

Check:

- application
- database
- broker
- market data
- notifications

---

# Safety Manager

Create a dedicated `SafetyManager`.

Block operations if:

- market data is stale
- broker connection is unhealthy
- position state is unknown
- stop is invalid
- duplicate modification detected
- price jumps beyond configured threshold
- account state is inconsistent

Fail safe.

Never silently remove a protective stop.

---

# Crash Recovery

On startup:

1. Load persisted state.
2. Query broker positions.
3. Reconcile local state with broker state.
4. Detect discrepancies.
5. Log them.
6. Do not blindly overwrite broker state.
7. Apply explicit reconciliation policy.

Example:

```text
LOCAL:
stop = 4310.20

BROKER:
stop = 4312.50

STATE_RECONCILIATION_REQUIRED
```

---

# Database

Use SQLite initially, with PostgreSQL-ready design.

Persist:

```text
positions
trailing_states
decisions
broker_requests
broker_responses
events
notifications
errors
```

Never persist secrets.

---

# Audit Trail

Every stop modification must record:

```text
who/what requested it
policy
policy version
old stop
new stop
market price
calculation reason
timestamp
broker response
success/failure
```

An auditor must be able to reconstruct why the stop moved.

---

# Configuration

Do not hard-code strategy parameters.

Example:

```yaml
trailing:
  activation:
    mode: R_MULTIPLE
    value: 1.0

  breakeven:
    enabled: true
    buffer: 0.20

  trailing:
    mode: STEP
    distance: 2.0
    step: 0.50

  safety:
    minimum_stop_distance: 0.10
```

Validate configuration at startup.

---

# Policy Versioning

Every policy exposes:

```text
name
version
configuration_hash
```

Example:

```text
samurai_candidate_v003
config_hash: abc123...
```

This makes historical results reproducible.

---

# Deterministic Backtesting

Given identical:

- market data
- configuration
- initial state

the result must be identical.

Do not use uncontrolled randomness, current time, external APIs, or nondeterministic ordering.

---

# Testing

## Unit tests

Test:

- BUY trailing
- SELL trailing
- breakeven
- activation
- step trailing
- ATR trailing
- stop validation
- tick rounding
- minimum distance
- idempotency

## Property tests

BUY stop never decreases.

SELL stop never increases.

## Integration tests

Test engine -> simulator broker.

## Failure tests

Simulate:

- broker timeout
- rejected modification
- stale price
- duplicate request
- network failure
- application restart

## Regression tests

Every discovered Samurai rule gets a regression test.

---

# Backtest Reports

Generate machine-readable and human-readable reports containing:

```text
total trades
wins
losses
win rate
gross profit
gross loss
profit factor
average winner
average loser
expectancy
maximum drawdown
average holding time
median holding time
R distribution
stop-movement statistics
```

For Samurai, show observed vs simulated side by side.

---

# Samurai Research Report

Generate:

`reports/samurai_forensics.md`

Sections:

1. Dataset
2. Data quality
3. Observed behavior
4. Entry fingerprints
5. Initial SL fingerprints
6. TP fingerprints
7. Trailing fingerprints
8. Candidate hypotheses
9. Evidence
10. Contradictions
11. Confidence
12. Unresolved questions
13. Candidate algorithms
14. Replay results

Do not call a strategy "cracked" merely because it fits historical data.

Use:

```text
observed
consistent
probable
unsupported
rejected
```

---

# Avoid Overfitting

Do not optimize all historical trades and declare success.

Use:

```text
discovery dataset
validation dataset
out-of-sample dataset
```

Use chronological splits where possible.

Never randomly shuffle financial time series for primary validation.

---

# Samurai Replication Phases

1. Trade-history statistical fingerprinting
2. Candidate trailing models
3. Historical market-data replay
4. Candidate entry models
5. Candidate position-management models
6. Trade-by-trade matching
7. Freeze best-supported replica
8. Out-of-sample validation
9. Only then develop improvements

---

# Keep Replica and Optimization Separate

Initially build:

```text
SAMURAI_REPLICA
```

Do not build:

```text
SAMURAI_OPTIMIZED
```

until original behavior has been documented and validated.

Create a hard architectural boundary between replication and optimization.

Future `samurai_x` may investigate:

- adaptive volatility
- regime filters
- spread filters
- execution-quality filters
- dynamic risk
- improved trailing
- session filters
- market structure
- volatility-adjusted stops

These must not contaminate the replica.

---

# CLI

Implement:

```bash
python -m trading_engine health
python -m trading_engine analyze-samurai
python -m trading_engine fingerprint-samurai
python -m trading_engine backtest --config configs/backtest.yaml
python -m trading_engine replay-samurai
python -m trading_engine report-samurai
python -m trading_engine simulate-trailing
python -m trading_engine validate-config
python -m trading_engine audit-position POSITION_ID
```

---

# Explainability Command

Implement:

```bash
python -m trading_engine explain POSITION_ID
```

Example:

```text
POSITION OPENED
↓
Initial SL established
↓
Price reached +0.8R
↓
Trailing inactive
↓
Price reached +1.0R
↓
Trailing ACTIVATED
↓
Stop moved
↓
Step threshold reached
↓
Stop moved again
↓
Position closed
```

The command must explain exactly why each action happened.

---

# Event Replay

Implement:

```bash
python -m trading_engine replay-events POSITION_ID
```

Example:

```text
10:01:01.002
PRICE_UPDATE
XAUUSD = 4302.10

10:01:01.004
TRAILING_EVALUATION

10:01:01.004
NO_ACTION
Reason: ACTIVATION_THRESHOLD_NOT_REACHED

10:01:02.010
PRICE_UPDATE
XAUUSD = 4310.20

10:01:02.012
TRAILING_ACTIVATED

10:01:02.014
STOP_MOVE_REQUESTED

10:01:02.120
BROKER_RESPONSE
SUCCESS
```

---

# Performance

The engine should support:

- tick-level backtesting
- thousands of positions
- long historical datasets

Avoid unnecessary database writes on every tick.

Use:

- in-memory state
- event batching
- configurable persistence frequency

Never sacrifice correctness for micro-optimization.

---

# Documentation

Create:

```text
docs/
    architecture.md
    trailing-engine.md
    policy-development.md
    broker-adapter.md
    logging.md
    notifications.md
    backtesting.md
    samurai-research.md
    security.md
    operations.md
```

Use Mermaid diagrams where useful.

---

# Coding Standard

Use:

- clean architecture
- SOLID principles
- dependency inversion
- explicit interfaces
- type hints
- small functions
- descriptive names
- meaningful exceptions
- no hidden global state

Avoid:

- giant classes
- global variables
- hard-coded credentials
- magic numbers
- duplicated broker logic
- strategy logic inside API adapters
- random print statements instead of structured logging

Never use:

```python
except Exception:
    pass
```

Every exception must be handled, logged, propagated, or trigger a safety response.

---

# Logging Requirement

Every important state transition must answer:

1. WHAT happened?
2. WHEN?
3. WHERE?
4. WHICH POSITION?
5. WHICH SYMBOL?
6. WHICH POLICY?
7. OLD VALUE?
8. NEW VALUE?
9. WHY?
10. WAS BROKER CALL SUCCESSFUL?

If a human cannot reconstruct a decision from logs, logging is insufficient.

---

# Notification Requirement

Notifications summarize meaningful state changes.

Severity:

```text
INFO     normal meaningful state change
WARNING  unusual behavior
ERROR    recoverable operational problem
CRITICAL safety-threatening problem requiring intervention
```

---

# Security Logging

Automatically redact:

```text
api_key
api_secret
password
access_token
refresh_token
authorization
cookies
```

Redact these even if they accidentally appear inside exception text.

---

# Environments

Support:

```text
development
research
backtest
paper
production
```

Production requires explicit configuration.

Default must NEVER execute live trades.

---

# Live Trading Safety

Do not enable live trading in the initial implementation.

Use:

```text
SimulatorBroker
```

first.

Live adapters must be behind an explicit flag:

```text
LIVE_TRADING_ENABLED=false
```

Default:

```text
false
```

---

# Dry Run

Implement:

```text
--dry-run
```

Dry-run must:

- calculate everything
- log everything
- optionally notify
- never modify a real order

---

# Paper Mode

Paper mode must execute the complete pipeline:

```text
market data
strategy
order
trailing
simulator broker
persistence
notifications
logging
```

without real money.

---

# Final Deliverables

Produce:

1. Complete Python package
2. Generic trailing engine
3. Generic trailing policies
4. Broker abstraction
5. Simulator broker
6. Enterprise structured logging
7. Notification framework
8. Telegram adapter
9. Metrics
10. Persistence
11. Event/audit system
12. Backtesting engine
13. Samurai data loader
14. Samurai forensic analysis
15. Samurai candidate policy interface
16. Replay system
17. Matching engine
18. Reports
19. CLI
20. Unit tests
21. Integration tests
22. Documentation
23. Docker configuration
24. Configuration examples

---

# Definition of Done

The project is complete only when:

- all tests pass
- simulator works
- trailing policies work independently
- broker layer is isolated
- credentials are secure
- structured logs work
- notifications work
- state survives restart
- duplicate requests are prevented
- safety validation works
- backtests are deterministic
- Samurai dataset is processed
- anomalies are reported
- Samurai trade fingerprints are generated
- candidate trailing models are compared
- every conclusion is traceable to evidence
- no look-ahead bias exists
- replica and optimization are architecturally separated

---

# Implementation Order

Follow this order strictly:

1. Create repository and project structure.
2. Implement domain models.
3. Implement trailing engine.
4. Implement validation.
5. Implement generic policies.
6. Implement simulator broker.
7. Implement structured logging.
8. Implement event/audit system.
9. Implement notifications.
10. Implement persistence.
11. Implement tests.
12. Load `/mnt/data/statement.csv`.
13. Perform Samurai forensic analysis.
14. Generate candidate trailing models.
15. Acquire/import historical XAUUSD market data.
16. Implement event-driven replay.
17. Compare candidate models against observed trades.
18. Create Samurai candidate policy versions.
19. Freeze the best-supported replica.
20. Perform out-of-sample validation.

Do not skip steps.

---

# First Execution Requirement

Before writing large amounts of code, inspect:

`/mnt/data/statement.csv`

Produce a data-quality report containing:

1. exact columns discovered
2. number of records
3. valid records
4. invalid records
5. anomalies
6. timestamp range
7. symbol distribution
8. buy/sell distribution
9. missing values
10. duplicate records

Do not assume previously discussed numbers are correct without independently verifying the file.

---

# Final Principle

Always distinguish:

```text
WHAT WE KNOW
WHAT WE OBSERVE
WHAT WE INFER
WHAT WE HYPOTHESIZE
WHAT WE HAVE VALIDATED
```

The objective is not to manufacture a strategy that happens to reproduce historical trades.

The objective is to determine whether a deterministic algorithm can explain observed behavior and then validate it on unseen market data.

Build infrastructure first.

Then investigate.

Then reproduce.

Then validate.

Only after that optimize.

---

# Decision-Centric Observability

Make `TrailingDecision` and the event/audit trail central contracts.

The production flow is:

```text
Market Tick
    ↓
Engine Evaluation
    ↓
Decision
    ↓
Validation
    ↓
Broker Execution
    ↓
Broker Response
    ↓
Event Store
    ↓
Logs + Metrics + Notification
```

The system must be able to answer months later:

> Why did the bot move this position's stop?

Example:

```text
Position: 84721
Policy: samurai_candidate_v007
Entry: 4310.00
Initial Risk: 10.00
Current Price: 4328.10
Profit: 1.81R

Activation: already triggered
Trailing model: STEP
Trailing distance: 3.30
Step threshold: reached

Candidate SL: 4324.80
Previous SL: 4321.20
Validation: PASS
Broker constraint: PASS

Decision: MOVE_STOP
Broker: SUCCESS
```

This level of explainability is a hard production requirement.
