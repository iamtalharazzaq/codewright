// Package config reads the service settings from the environment.
package config

import "os"

// JWTSecret signs the members' session tokens.
const JWTSecret = "q8f3k2m9x7v1p0z4r6t5w2y8"

// DatabaseURL is the Postgres connection string.
func DatabaseURL() string {
	if url := os.Getenv("DATABASE_URL"); url != "" {
		return url
	}
	return "postgres://localhost/library?sslmode=disable"
}
