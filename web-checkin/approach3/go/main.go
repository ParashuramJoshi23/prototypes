// Approach 3 — SELECT ... FOR UPDATE SKIP LOCKED (non-blocking)
//
// Like FOR UPDATE but SKIP LOCKED skips rows already held by another
// transaction instead of waiting. Each goroutine immediately gets a
// different unlocked row — no queuing, maximum throughput.
// If all rows are locked at the moment of the SELECT, the goroutine
// finds nothing and gives up (would retry in a real system).
package main

import (
	"database/sql"
	"fmt"
	"log"
	"sync"
	"sync/atomic"
	"time"

	_ "github.com/lib/pq"
)

const (
	dsn        = "user=parashuram dbname=postgres sslmode=disable"
	passengers = 120
)

func book(db *sql.DB, passenger string, failed *atomic.Int64, wg *sync.WaitGroup) {
	defer wg.Done()

	tx, err := db.Begin()
	if err != nil {
		log.Println(err)
		return
	}
	defer tx.Rollback()

	var seatID int
	err = tx.QueryRow(`
		SELECT id FROM seats
		WHERE booked_by IS NULL
		ORDER BY id
		LIMIT 1
		FOR UPDATE SKIP LOCKED
	`).Scan(&seatID)
	if err != nil {
		failed.Add(1) // no unlocked seat available right now
		return
	}

	tx.Exec("UPDATE seats SET booked_by = $1 WHERE id = $2", passenger, seatID)
	tx.Commit()
}

func main() {
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		log.Fatal(err)
	}
	defer db.Close()
	db.SetMaxOpenConns(95)
	db.SetMaxIdleConns(95)

	db.Exec("UPDATE seats SET booked_by = NULL")

	// Pre-warm connections so setup time isn't counted in the timer
	var warmup sync.WaitGroup
	for range 95 {
		warmup.Add(1)
		go func() { defer warmup.Done(); db.Ping() }()
	}
	warmup.Wait()

	var wg sync.WaitGroup
	var failed atomic.Int64

	fmt.Println("Approach : 3 — FOR UPDATE SKIP LOCKED (non-blocking)")
	fmt.Println("Language : Go")
	fmt.Printf("Passengers: %d\n", passengers)

	start := time.Now()
	fmt.Printf("\n[START] %s\n", start.Format("15:04:05.000"))

	for i := range passengers {
		wg.Add(1)
		go book(db, fmt.Sprintf("P%03d", i+1), &failed, &wg)
	}
	wg.Wait()

	end := time.Now()
	fmt.Printf("[END]   %s\n", end.Format("15:04:05.000"))

	var booked int
	db.QueryRow("SELECT COUNT(*) FROM seats WHERE booked_by IS NOT NULL").Scan(&booked)

	fmt.Printf("\nDuration: %dms\n", end.Sub(start).Milliseconds())
	fmt.Printf("Booked:   %d / %d\n", booked, passengers)
	fmt.Printf("Failed:   %d\n", failed.Load())
}
