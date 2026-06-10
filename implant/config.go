package main

// Override at build time: -ldflags="-X main.serverURL=https://..."
var serverURL = "https://127.0.0.1:8443"

func GetServerURL() string {
	return serverURL
}
