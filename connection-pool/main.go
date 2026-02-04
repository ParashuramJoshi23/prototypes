package main

import (
	"database/sql"
	"fmt"
	"log"
	"os"
	"time"

	_ "github.com/go-sql-driver/mysql"
)

var dsn string

const (
	defaultDSN        = "root@tcp(127.0.0.1:3306)/test"
	defaultIterations = 500
)

func main() {
	dsn = os.Getenv("MYSQL_DSN")
	if dsn == "" {
		dsn = defaultDSN
	}

	x := defaultIterations

	fmt.Printf("Running %d iterations each...\n\n", x)

	// Benchmark without pooling (new connection per query)
	nonPoolDuration := benchmarkNonPool(x)
	fmt.Printf("Non-Pool: %v (avg: %v per query)\n", nonPoolDuration, nonPoolDuration/time.Duration(x))

	// Benchmark with pooling (reuse connections)
	poolDuration := benchmarkPool(x)
	fmt.Printf("Pool:     %v (avg: %v per query)\n", poolDuration, poolDuration/time.Duration(x))

	// Summary
	fmt.Printf("\nPooling is %.2fx faster\n", float64(nonPoolDuration)/float64(poolDuration))
}

func newConn() *sql.DB {
	db, err := sql.Open("mysql", dsn)
	if err != nil {
		log.Fatal(err)
	}
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(0)
	return db
}

// benchmarkNonPool opens a new connection for each query (simulates no pooling)
func benchmarkNonPool(x int) time.Duration {
	start := time.Now()

	for i := 0; i < x; i++ {
		db := newConn()

		_, err := db.Exec("SELECT 1")
		if err != nil {
			log.Fatal(err)
			continue
		}

		db.Close()
	}

	return time.Since(start)
}

// benchmarkPool uses connection pooling (reuses connections)
func benchmarkPool(x int) time.Duration {
	db, err := sql.Open("mysql", dsn)
	if err != nil {
		log.Fatal(err)
	}
	defer db.Close()

	db.SetMaxOpenConns(50)
	db.SetMaxIdleConns(10)
	db.SetConnMaxLifetime(time.Minute * 5)

	db.Ping()

	start := time.Now()

	for i := 0; i < x; i++ {
		_, err := db.Exec("SELECT 1")
		if err != nil {
			log.Fatal(err)
		}
	}

	return time.Since(start)
}
