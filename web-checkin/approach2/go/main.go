// Approach 2 — SELECT ... FOR UPDATE (blocking)
//
// Each goroutine opens a transaction, locks the first available row
// with FOR UPDATE, updates it, and commits. Concurrent transactions
// that target the same row block until the lock is released, then
// re-evaluate.
package main

import (
	"database/sql"
	"fmt"
	"log"
	"sync"
	"time"

	_ "github.com/lib/pq"
)

const (
	dsn        = "user=parashuram dbname=postgres sslmode=disable"
	passengers = 120
)

func book(db *sql.DB, passenger string, wg *sync.WaitGroup) {
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
		FOR UPDATE
	`).Scan(&seatID)
	if err != nil {
		return // no seats left
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

	fmt.Println("Approach : 2 — FOR UPDATE (blocking)")
	fmt.Println("Language : Go")
	fmt.Printf("Passengers: %d\n", passengers)

	start := time.Now()
	fmt.Printf("\n[START] %s\n", start.Format("15:04:05.000"))

	for i := range passengers {
		wg.Add(1)
		go book(db, fmt.Sprintf("P%03d", i+1), &wg)
	}
	wg.Wait()

	end := time.Now()
	fmt.Printf("[END]   %s\n", end.Format("15:04:05.000"))

	var booked int
	db.QueryRow("SELECT COUNT(*) FROM seats WHERE booked_by IS NOT NULL").Scan(&booked)

	fmt.Printf("\nDuration: %dms\n", end.Sub(start).Milliseconds())
	fmt.Printf("Booked:   %d / %d\n", booked, passengers)
}
