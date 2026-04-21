// Approach 1 — No Lock (race condition)
//
// SELECT then UPDATE with no transaction or lock.
// A 5ms sleep widens the window between read and write so multiple
// goroutines see the same seat as free and overwrite each other.
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

	var seatID int
	err := db.QueryRow(`
		SELECT id FROM seats
		WHERE booked_by IS NULL
		ORDER BY id
		LIMIT 1
	`).Scan(&seatID)
	if err != nil {
		return
	}

	time.Sleep(5 * time.Millisecond) // widen race window

	db.Exec("UPDATE seats SET booked_by = $1 WHERE id = $2", passenger, seatID)
}

func main() {
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		log.Fatal(err)
	}
	defer db.Close()
	db.SetMaxOpenConns(150)

	db.Exec("UPDATE seats SET booked_by = NULL")

	var wg sync.WaitGroup

	fmt.Println("Approach : 1 — No Lock")
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
