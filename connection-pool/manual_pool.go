package main

import (
	"database/sql"
	"fmt"
	"log"
	"sync"
	"time"

	_ "github.com/go-sql-driver/mysql"
)

type ManualPool struct {
	mu          sync.Mutex
	connections chan *sql.DB
	dsn         string
	maxSize     int
}

func NewManualPool(dsn string, maxSize int) *ManualPool {
	pool := &ManualPool{
		connections: make(chan *sql.DB, maxSize),
		dsn:         dsn,
		maxSize:     maxSize,
	}

	// Pre-create connections
	for i := 0; i < maxSize; i++ {
		conn, err := sql.Open("mysql", dsn)
		if err != nil {
			log.Fatal(err)
		}
		conn.SetMaxOpenConns(1)
		conn.SetMaxIdleConns(1)
		pool.connections <- conn
	}

	return pool
}

// Get blocks until a connection is available
func (p *ManualPool) Get() *sql.DB {
	return <-p.connections
}

// Put returns a connection to the pool
func (p *ManualPool) Put(conn *sql.DB) {
	p.connections <- conn
}

// Close closes all connections in the pool
func (p *ManualPool) Close() {
	close(p.connections)
	for conn := range p.connections {
		conn.Close()
	}
}

func main() {
	dsn := "root@tcp(127.0.0.1:3306)/test"
	numWorkers := 50
	queriesPerWorker := 100

	fmt.Printf("Workers: %d, Queries per worker: %d\n", numWorkers, queriesPerWorker)
	fmt.Printf("Total queries: %d\n\n", numWorkers*queriesPerWorker)

	// Benchmark without pool (each goroutine creates its own connection)
	fmt.Println("Running Non-Pool benchmark...")
	nonPoolDuration := benchmarkNonPoolConcurrent(dsn, numWorkers, queriesPerWorker)
	fmt.Printf("Non-Pool: %v\n\n", nonPoolDuration)

	// Benchmark with manual pool
	fmt.Println("Running Manual Pool benchmark...")
	poolDuration := benchmarkManualPool(dsn, numWorkers, queriesPerWorker)
	fmt.Printf("Manual Pool: %v\n\n", poolDuration)

	fmt.Printf("Manual Pool is %.2fx faster\n", float64(nonPoolDuration)/float64(poolDuration))
}

func benchmarkNonPoolConcurrent(dsn string, numWorkers, queriesPerWorker int) time.Duration {
	var wg sync.WaitGroup
	start := time.Now()

	for w := 0; w < numWorkers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()

			for q := 0; q < queriesPerWorker; q++ {
				// Create new connection for each query (no pooling)
				db, err := sql.Open("mysql", dsn)
				if err != nil {
					log.Fatal(err)
				}
				db.SetMaxOpenConns(1)
				db.SetMaxIdleConns(0)

				_, err = db.Exec("SELECT 1")
				if err != nil {
					log.Fatal(err)
				}
				db.Close()
			}
		}()
	}

	wg.Wait()
	return time.Since(start)
}

func benchmarkManualPool(dsn string, numWorkers, queriesPerWorker int) time.Duration {
	pool := NewManualPool(dsn, 10) // Pool of 10 connections
	defer pool.Close()

	var wg sync.WaitGroup
	start := time.Now()

	for w := 0; w < numWorkers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()

			for q := 0; q < queriesPerWorker; q++ {
				// Get connection from pool (blocks if none available)
				conn := pool.Get()

				_, err := conn.Exec("SELECT 1")
				if err != nil {
					log.Fatal(err)
				}

				// Return connection to pool
				pool.Put(conn)
			}
		}()
	}

	wg.Wait()
	return time.Since(start)
}
