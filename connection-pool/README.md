# MySQL Connection Pooling Benchmark

Compares performance of connection pooling vs creating new connections per query.

## Setup

```bash
# Install dependency
go mod init connection-pool
go mod tidy
```

## Run

```bash
# Default: connects to root:password@tcp(127.0.0.1:3306)/test
go run main.go

# Custom connection string
MYSQL_DSN="user:pass@tcp(host:3306)/dbname" go run main.go
```

## What it does

- **benchmarkNonPool**: Opens and closes a new connection for each query
- **benchmarkPool**: Reuses connections from a pool

The output shows total time and average time per query for each approach.



  ┌───────────┬────────┬───────────────┐
  │ Benchmark │ Total  │ Avg per query │
  ├───────────┼────────┼───────────────┤
  │ Non-Pool  │ 95.8ms │ 191.7µs       │
  ├───────────┼────────┼───────────────┤
  │ Pool      │ 13.6ms │ 27.2µs        │
  └───────────┴────────┴───────────────┘
  Pooling is 7.05x faster

  The connection overhead (~165µs per query) is now visible because SELECT 1 executes in
  microseconds. This is why pooling matters for fast, frequent queries.