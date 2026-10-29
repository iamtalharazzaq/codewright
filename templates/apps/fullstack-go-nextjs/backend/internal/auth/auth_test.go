package auth

import (
	"encoding/hex"
	"testing"
	"time"
)

func TestPBKDF2KnownVector(t *testing.T) {
	// RFC 7914 section 11: PBKDF2-HMAC-SHA-256("passwd", "salt", 1, 64) starts with 55ac046e
	got := hex.EncodeToString(pbkdf2([]byte("passwd"), []byte("salt"), 1, 16))
	if got != "55ac046e56e3089fec1691c22544b605" {
		t.Fatalf("got %s", got)
	}
}

func TestPasswords(t *testing.T) {
	Iterations = 1000
	stored := HashPassword("correct horse")
	if !CheckPassword("correct horse", stored) || CheckPassword("wrong", stored) || CheckPassword("x", "garbage") {
		t.Fatal("password check is wrong")
	}
}

func TestTokens(t *testing.T) {
	now := time.Unix(1_000, 0)
	token := MakeToken("s3cret", 7, now)
	if id, ok := ReadToken("s3cret", token, now.Add(time.Minute)); !ok || id != 7 {
		t.Fatalf("got %d %v", id, ok)
	}
	if _, ok := ReadToken("s3cret", token, now.Add(8*24*time.Hour)); ok {
		t.Fatal("an expired token was accepted")
	}
	if _, ok := ReadToken("other", token, now); ok {
		t.Fatal("a token signed with another secret was accepted")
	}
	if _, ok := ReadToken("s3cret", "garbage", now); ok {
		t.Fatal("garbage was accepted")
	}
}
