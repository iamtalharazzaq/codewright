// Package auth hashes passwords and signs sign-in tokens, with the standard library only.
package auth

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"strings"
	"time"
)

// Iterations is the PBKDF2 work factor.
var Iterations = 120_000

// TokenLife is how long a token stays valid.
const TokenLife = 7 * 24 * time.Hour

// HashPassword returns "salt$hash" (both hex).
func HashPassword(password string) string {
	salt := make([]byte, 16)
	_, _ = rand.Read(salt)
	return hex.EncodeToString(salt) + "$" + hex.EncodeToString(pbkdf2([]byte(password), salt, Iterations, 32))
}

// CheckPassword reports whether password matches a value made by HashPassword.
func CheckPassword(password, stored string) bool {
	saltHex, hashHex, ok := strings.Cut(stored, "$")
	if !ok {
		return false
	}
	salt, err := hex.DecodeString(saltHex)
	if err != nil {
		return false
	}
	got := hex.EncodeToString(pbkdf2([]byte(password), salt, Iterations, 32))
	return subtle.ConstantTimeCompare([]byte(got), []byte(hashHex)) == 1
}

type claims struct {
	Sub int   `json:"sub"`
	Exp int64 `json:"exp"`
}

// MakeToken signs a token for userID that expires TokenLife after now.
func MakeToken(secret string, userID int, now time.Time) string {
	raw, _ := json.Marshal(claims{Sub: userID, Exp: now.Add(TokenLife).Unix()})
	payload := base64.URLEncoding.EncodeToString(raw)
	return payload + "." + sign(secret, payload)
}

// ReadToken returns the user id in a valid, unexpired token.
func ReadToken(secret, token string, now time.Time) (int, bool) {
	payload, signature, ok := strings.Cut(token, ".")
	if !ok || !hmac.Equal([]byte(sign(secret, payload)), []byte(signature)) {
		return 0, false
	}
	raw, err := base64.URLEncoding.DecodeString(payload)
	if err != nil {
		return 0, false
	}
	var c claims
	if json.Unmarshal(raw, &c) != nil || c.Exp < now.Unix() || c.Sub < 1 {
		return 0, false
	}
	return c.Sub, true
}

func sign(secret, payload string) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(payload))
	return hex.EncodeToString(mac.Sum(nil))
}

// pbkdf2 is PBKDF2-HMAC-SHA256 (RFC 8018).
func pbkdf2(password, salt []byte, iterations, keyLen int) []byte {
	prf := hmac.New(sha256.New, password)
	var out []byte
	for block := 1; len(out) < keyLen; block++ {
		prf.Reset()
		prf.Write(salt)
		prf.Write([]byte{byte(block >> 24), byte(block >> 16), byte(block >> 8), byte(block)})
		u := prf.Sum(nil)
		t := append([]byte(nil), u...)
		for n := 2; n <= iterations; n++ {
			prf.Reset()
			prf.Write(u)
			u = prf.Sum(u[:0])
			for i := range t {
				t[i] ^= u[i]
			}
		}
		out = append(out, t...)
	}
	return out[:keyLen]
}
